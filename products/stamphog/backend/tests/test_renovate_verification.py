import json
from typing import Any

from django.test import SimpleTestCase

import yaml
from parameterized import parameterized

from products.stamphog.backend.logic.renovate_verification import (
    RENOVATE_BOT_LOGIN,
    RENOVATE_BOT_USER_ID,
    VersionChange,
    changed_file_problems,
    commit_problems,
    is_renovate_pr,
    manifest_changed_specifiers,
    package_json_problems,
    pnpm_lock_versions,
    pnpm_policy_problems,
    update_refusal,
    verify_renovate_update,
)

REPO = "PostHog/posthog"
HEAD = "b" * 40
_PNPM_POLICY = "minimumReleaseAge: 10080\ntrustPolicy: no-downgrade\n"


def _renovate_pr(**overrides: Any) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "user": {"type": "Bot", "id": RENOVATE_BOT_USER_ID, "login": RENOVATE_BOT_LOGIN},
        "head": {"ref": "renovate/npm-non-major", "repo": {"full_name": REPO}},
    }
    return {**pr, **overrides}


def _commit(sha: str = HEAD, author_id: int = RENOVATE_BOT_USER_ID, verified: bool = True) -> dict[str, Any]:
    return {
        "sha": sha,
        "author": {"id": author_id},
        "committer": {"login": "web-flow"},
        "commit": {"verification": {"verified": verified}},
    }


def _pnpm_lock(packages: dict[str, dict[str, Any]], **top_level: Any) -> str:
    return yaml.safe_dump(
        {"lockfileVersion": "9.0", "settings": {"autoInstallPeers": True}, **top_level, "packages": packages}
    )


class TestRenovateIdentity(SimpleTestCase):
    @parameterized.expand(
        [
            ("genuine", {}, True),
            ("fork_head", {"head": {"ref": "renovate/x", "repo": {"full_name": "attacker/posthog"}}}, False),
            ("non_renovate_branch", {"head": {"ref": "feature/x", "repo": {"full_name": REPO}}}, False),
            ("other_bot_same_login", {"user": {"type": "Bot", "id": 1, "login": RENOVATE_BOT_LOGIN}}, False),
            ("human", {"user": {"type": "User", "id": RENOVATE_BOT_USER_ID, "login": RENOVATE_BOT_LOGIN}}, False),
        ]
    )
    def test_is_renovate_pr(self, _name: str, overrides: dict[str, Any], expected: bool) -> None:
        assert is_renovate_pr(_renovate_pr(**overrides), REPO) is expected

    @parameterized.expand(
        [
            ("renovate_only", [_commit()], []),
            ("second_commit", [_commit("a" * 40), _commit()], ["not exactly one commit"]),
            ("other_author", [_commit(author_id=42)], ["not authored by"]),
            ("unsigned", [_commit(verified=False)], ["not committed and signed"]),
            ("stale_head", [_commit("a" * 40)], ["not the reviewed head"]),
        ]
    )
    def test_commit_problems(self, _name: str, commits: list[dict[str, Any]], expected: list[str]) -> None:
        problems = commit_problems(commits, HEAD)
        assert len(problems) == len(expected)
        assert all(fragment in problem for fragment, problem in zip(expected, problems))

    @parameterized.expand(
        [
            ("lock_and_manifest", [("pnpm-lock.yaml", "modified"), ("package.json", "modified")], None),
            (
                "source_file",
                [("pnpm-lock.yaml", "modified"), ("frontend/src/index.ts", "modified")],
                "not an npm manifest",
            ),
            ("python_lockfile", [("pnpm-lock.yaml", "modified"), ("uv.lock", "modified")], "not an npm manifest"),
            ("added_manifest", [("pnpm-lock.yaml", "modified"), ("tools/x/package.json", "added")], "added"),
            ("manifest_only", [("package.json", "modified")], "no pnpm-lock.yaml"),
        ]
    )
    def test_changed_file_problems(self, _name: str, files: list[tuple[str, str]], expected: str | None) -> None:
        problems = changed_file_problems([{"filename": path, "status": status} for path, status in files])
        assert (problems == []) if expected is None else (expected in problems[0])


class TestManifestProblems(SimpleTestCase):
    @parameterized.expand(
        [
            ("range_bump", {"dependencies": {"left-pad": "^1.1.0"}}, None),
            ("new_dependency", {"dependencies": {"left-pad": "^1.0.0", "evil": "1.0.0"}}, "adds or removes"),
            ("protocol_redirect", {"dependencies": {"left-pad": "npm:evil@1.0.0"}}, "caret or tilde"),
            ("tarball_redirect", {"dependencies": {"left-pad": "https://example.com/x.tgz"}}, "caret or tilde"),
            ("dist_tag", {"dependencies": {"left-pad": "latest"}}, "caret or tilde"),
            ("open_range", {"dependencies": {"left-pad": ">=1.1.0"}}, "caret or tilde"),
            ("script_change", {"dependencies": {"left-pad": "^1.0.0"}, "scripts": {"postinstall": "curl"}}, "other"),
        ]
    )
    def test_package_json(self, _name: str, head: dict[str, Any], expected: str | None) -> None:
        base = {"name": "app", "dependencies": {"left-pad": "^1.0.0"}}
        problems = package_json_problems("package.json", json.dumps(base), json.dumps(head | {"name": "app"}))
        assert (problems == []) if expected is None else (expected in problems[0])

    @parameterized.expand(
        [
            ("enforced", _PNPM_POLICY, True),
            ("no_workspace", None, False),
            ("no_release_age", "trustPolicy: no-downgrade\n", False),
            ("loose_release_age", _PNPM_POLICY + "minimumReleaseAgeStrict: false\n", False),
            ("no_trust_policy", "minimumReleaseAge: 10080\n", False),
            ("every_build_allowed", _PNPM_POLICY + "dangerouslyAllowAllBuilds: true\n", False),
            ("other_package_exempt", _PNPM_POLICY + "minimumReleaseAgeExclude:\n  - right-pad\n", True),
            ("age_exempt_by_glob", _PNPM_POLICY + "minimumReleaseAgeExclude:\n  - left-*\n", False),
            ("trust_exempt_by_version", _PNPM_POLICY + "trustPolicyExclude:\n  - left-pad@1.1.0 || 1.2.0\n", False),
        ]
    )
    def test_pnpm_policy_problems(self, _name: str, workspace: str | None, enforced: bool) -> None:
        change = VersionChange(name="left-pad", old_version="1.0.0", new_version="1.1.0")
        assert (pnpm_policy_problems("pnpm-workspace.yaml", workspace, [change]) == []) is enforced

    def test_manifest_changed_specifiers_reads_named_catalogs(self) -> None:
        assert manifest_changed_specifiers(
            "pnpm-workspace.yaml",
            "catalogs:\n  react:\n    react: ^18.0.0\n    scheduler: ^0.23.0\n",
            "catalogs:\n  react:\n    react: ^18.3.0\n    scheduler: ^0.23.0\n",
        ) == {("react", "^18.3.0")}


class TestLockfileVersions(SimpleTestCase):
    @parameterized.expand(
        [
            ("patch", "1.2.3", "1.2.4", None),
            ("minor", "1.2.3", "1.3.0", None),
            ("major", "1.9.0", "2.0.0", "a major update"),
            ("zero_minor", "0.4.1", "0.5.0", "a major update"),
            ("zero_patch", "0.4.1", "0.4.2", None),
            ("calendar_major", "2024.10.1", "2025.1.0", "a major update"),
            ("not_numeric", "1.0.0", "next", "a major update"),
            ("patch_downgrade", "1.2.4", "1.2.3", "a downgrade"),
            ("minor_downgrade", "1.10.0", "1.9.5", "a downgrade"),
        ]
    )
    def test_update_refusal(self, _name: str, old: str, new: str, expected: str | None) -> None:
        assert update_refusal(VersionChange(name="left-pad", old_version=old, new_version=new)) == expected

    @parameterized.expand(
        [
            ("replaces_its_only_version", ["1.0.0"], ["1.1.0"], [("1.0.0", "1.1.0")]),
            ("sits_beside_another_major", ["10.0.0", "9.0.0"], ["10.0.0", "10.1.0", "9.0.0"], [("10.0.0", "10.1.0")]),
            (
                "pairs_zero_versions_by_minor",
                ["0.4.1", "0.5.0"],
                ["0.4.2", "0.5.1"],
                [("0.4.1", "0.4.2"), ("0.5.0", "0.5.1")],
            ),
        ]
    )
    def test_pnpm_bump_yields_the_version_change(
        self, _name: str, base_versions: list[str], head_versions: list[str], expected: list[tuple[str, str]]
    ) -> None:
        def lock(versions: list[str]) -> str:
            return _pnpm_lock({f"left-pad@{v}": {"resolution": {"integrity": "sha512-new"}} for v in versions})

        changes, problems = pnpm_lock_versions("pnpm-lock.yaml", lock(base_versions), lock(head_versions))

        assert problems == []
        assert changes == [VersionChange(name="left-pad", old_version=old, new_version=new) for old, new in expected]

    @parameterized.expand(
        [
            ("new_transitive", {"evil@1.0.0": {"resolution": {"integrity": "sha512-x"}}}, "adds evil"),
            (
                "tarball",
                {"left-pad@1.1.0": {"resolution": {"integrity": "sha512-x", "tarball": "https://x"}}},
                "registry",
            ),
            (
                "same_version_new_hash",
                {"left-pad@1.0.0": {"resolution": {"integrity": "sha512-swapped"}}},
                "resolution",
            ),
        ]
    )
    def test_pnpm_refuses(self, _name: str, head_packages: dict[str, Any], expected: str) -> None:
        base = _pnpm_lock({"left-pad@1.0.0": {"resolution": {"integrity": "sha512-old"}}})
        _, problems = pnpm_lock_versions("pnpm-lock.yaml", base, _pnpm_lock(head_packages))
        assert expected in problems[0]

    @parameterized.expand(
        [
            ("locked_version", "1.1.0", "1.1.0", None),
            ("link_to_a_directory", "link:../evil", "1.1.0", "through something other than a locked version"),
            ("alias_to_another_package", "lodash@4.17.21", "1.1.0", "through something other than a locked version"),
            ("snapshot_points_at_a_file", "1.1.0", "file:../evil", "through something other than a locked version"),
            ("importer_moves_to_a_locked_major", "2.0.0", "1.1.0", "a major update"),
            ("snapshot_moves_to_a_locked_major", "1.1.0", "2.0.0", "a major update"),
            ("snapshot_substitutes_a_package", "1.1.0", "lodash@4.17.21", "another package for left-pad"),
        ]
    )
    def test_pnpm_references_must_select_a_locked_package(
        self, _name: str, importer_version: str, snapshot_reference: str, expected: str | None
    ) -> None:
        def lock(left_pad: str, importer: str, snapshot: str) -> str:
            return _pnpm_lock(
                {
                    f"left-pad@{left_pad}": {"resolution": {"integrity": f"sha512-{left_pad}"}},
                    "left-pad@2.0.0": {"resolution": {"integrity": "sha512-2.0.0"}},
                    "lodash@4.17.21": {"resolution": {"integrity": "sha512-lodash"}},
                },
                importers={".": {"dependencies": {"left-pad": {"specifier": "^1.0.0", "version": importer}}}},
                snapshots={"lodash@4.17.21": {"dependencies": {"left-pad": snapshot}}},
            )

        _, problems = pnpm_lock_versions(
            "pnpm-lock.yaml",
            lock("1.0.0", "1.0.0", "1.0.0"),
            lock("1.1.0", importer_version, snapshot_reference),
        )

        assert (problems == []) if expected is None else (expected in problems[0])

    @parameterized.expand(
        [
            ("alias_the_base_locked", "web-vitals@6.2.1", None),
            ("new_alias", "lodash@4.17.21", "another package"),
            ("alias_another_package_declared", "right-pad@1.0.0", "another package"),
        ]
    )
    def test_pnpm_new_snapshot_keeps_its_package_aliases(
        self, _name: str, reference: str, expected: str | None
    ) -> None:
        def lock(left_pad: str, vitals: str) -> str:
            return _pnpm_lock(
                {
                    f"left-pad@{left_pad}": {"resolution": {"integrity": f"sha512-{left_pad}"}},
                    "web-vitals@6.2.1": {"resolution": {"integrity": "sha512-vitals"}},
                    "lodash@4.17.21": {"resolution": {"integrity": "sha512-lodash"}},
                    "right-pad@1.0.0": {"resolution": {"integrity": "sha512-right"}},
                },
                snapshots={
                    f"left-pad@{left_pad}": {"dependencies": {"vitals": vitals}},
                    "lodash@4.17.21": {"dependencies": {"vitals": "right-pad@1.0.0"}},
                },
            )

        _, problems = pnpm_lock_versions("pnpm-lock.yaml", lock("1.0.0", "web-vitals@6.2.1"), lock("1.1.0", reference))

        assert (problems == []) if expected is None else (expected in problems[0])

    @parameterized.expand(
        [
            ("peers_resolve_again", {"left-pad": "1.1.0"}, None),
            ("peers_resolve_to_a_locked_major", {"left-pad": "2.0.0"}, "a major update"),
            ("adds_a_dependency", {"left-pad": "1.1.0", "right-pad": "1.0.0"}, "adds or removes a dependency"),
        ]
    )
    def test_pnpm_snapshot_renamed_by_its_peers_keeps_its_dependencies(
        self, _name: str, head_dependencies: dict[str, str], expected: str | None
    ) -> None:
        def lock(left_pad: str, react: str, dependencies: dict[str, str]) -> str:
            return _pnpm_lock(
                {
                    f"left-pad@{left_pad}": {"resolution": {"integrity": f"sha512-{left_pad}"}},
                    "left-pad@2.0.0": {"resolution": {"integrity": "sha512-2.0.0"}},
                    "right-pad@1.0.0": {"resolution": {"integrity": "sha512-right"}},
                    "lodash@4.17.21": {"resolution": {"integrity": "sha512-lodash"}},
                },
                snapshots={f"lodash@4.17.21(react@{react})": {"dependencies": dependencies}},
            )

        _, problems = pnpm_lock_versions(
            "pnpm-lock.yaml", lock("1.0.0", "18.0.0", {"left-pad": "1.0.0"}), lock("1.1.0", "18.1.0", head_dependencies)
        )

        assert (problems == []) if expected is None else (expected in problems[0])

    def test_pnpm_refuses_an_override_change(self) -> None:
        packages = {"left-pad@1.0.0": {"resolution": {"integrity": "sha512-old"}}}
        _, problems = pnpm_lock_versions(
            "pnpm-lock.yaml", _pnpm_lock(packages), _pnpm_lock(packages, overrides={"left-pad": "npm:evil@1"})
        )
        assert "overrides" in problems[0]


class TestVerifyRenovateUpdate(SimpleTestCase):
    @parameterized.expand(
        [
            ("clean_bump", {"right-pad": "^2.0.0"}, ()),
            (
                "specifier_without_relock",
                {"right-pad": "^3.0.0"},
                ("package.json changes the specifier of right-pad, and no lockfile locks a new version of it.",),
            ),
        ]
    )
    def test_a_bump_clears_its_lockfile_only_when_every_specifier_is_relocked(
        self, _name: str, head_dev_dependencies: dict[str, str], expected_problems: tuple[str, ...]
    ) -> None:
        files = {
            ("package.json", "base"): json.dumps(
                {"dependencies": {"left-pad": "^1.0.0"}, "devDependencies": {"right-pad": "^2.0.0"}}
            ),
            ("package.json", HEAD): json.dumps(
                {"dependencies": {"left-pad": "^1.1.0"}, "devDependencies": head_dev_dependencies}
            ),
            ("pnpm-lock.yaml", "base"): _pnpm_lock({"left-pad@1.0.0": {"resolution": {"integrity": "sha512-old"}}}),
            ("pnpm-lock.yaml", HEAD): _pnpm_lock({"left-pad@1.1.0": {"resolution": {"integrity": "sha512-new"}}}),
            ("pnpm-workspace.yaml", "base"): _PNPM_POLICY,
        }

        result = verify_renovate_update(
            pr=_renovate_pr(),
            repo=REPO,
            commits=[_commit()],
            files=[
                {"filename": "package.json", "status": "modified"},
                {"filename": "pnpm-lock.yaml", "status": "modified"},
            ],
            merge_base_sha="base",
            head_sha=HEAD,
            read_file=lambda path, ref: files.get((path, ref)),
        )

        assert result.problems == expected_problems
        assert result.verified is (not expected_problems)
        assert result.changes == (VersionChange(name="left-pad", old_version="1.0.0", new_version="1.1.0"),)
        assert result.cleared_paths == (() if expected_problems else ("pnpm-lock.yaml",))
