import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from unittest.mock import patch

from django.test import SimpleTestCase

import yaml
import requests
from parameterized import param, parameterized
from requests import HTTPError

from products.stamphog.backend.logic.renovate_verification import (
    RENOVATE_BOT_LOGIN,
    RENOVATE_BOT_USER_ID,
    RegistryReaders,
    VersionChange,
    _BaseRelease,
    _LockedFile,
    _NpmLockedVersion,
    _registry_problems,
    _UvLockedVersion,
    changed_file_problems,
    commit_problems,
    default_registry_readers,
    is_major_update,
    is_renovate_pr,
    manifest_changed_specifiers,
    npm_registry_problems,
    package_json_problems,
    pnpm_lock_versions,
    pypi_registry_problems,
    pyproject_problems,
    uv_lock_versions,
    verify_renovate_update,
)

_VERIFIER = "products.stamphog.backend.logic.renovate_verification"
REPO = "PostHog/posthog"
HEAD = "b" * 40
NOW = datetime(2026, 10, 26, tzinfo=UTC)
AGED = "2026-10-01T00:00:00Z"
FRESH = "2026-10-24T00:00:00Z"


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


def _uv_package(
    name: str,
    version: str,
    sha: str,
    source: str = '{ registry = "https://pypi.org/simple" }',
    dependencies: str = "",
) -> str:
    return (
        f'[[package]]\nname = "{name}"\nversion = "{version}"\nsource = {source}\n'
        + (f"dependencies = [{dependencies}]\n" if dependencies else "")
        + f'wheels = [{{ url = "https://files.pythonhosted.org/{name}-{version}-py3-none-any.whl", hash = "sha256:{sha}" }}]\n'
    )


def _uv_lock(*packages: str) -> str:
    return 'version = 1\nrevision = 5\nrequires-python = "==3.14.7"\n\n' + "\n".join(packages)


def _packument(old_dist: dict[str, Any], new_version: dict[str, Any], published: str = AGED) -> dict[str, Any]:
    return {
        "time": {"1.0.0": AGED, "1.1.0": published},
        "versions": {"1.0.0": {"dist": old_dist}, "1.1.0": new_version},
    }


_NPM_BUMP = _NpmLockedVersion(
    change=VersionChange(ecosystem="npm", name="left-pad", old_version="1.0.0", new_version="1.1.0"),
    integrity="sha512-new",
    base_versions=("1.0.0",),
)
_PROVENANCE = {"provenance": {"predicateType": "https://slsa.dev/provenance/v1"}}
_PYPI_FILES = "https://files.pythonhosted.org/packages/ab/cd"
_UNIVERSAL_WHEEL = "requests-2.33.0-py3-none-any.whl"
_LINUX_WHEEL = "requests-2.33.0-cp314-cp314-manylinux_2_28_x86_64.whl"
_WINDOWS_WHEEL = "requests-2.33.0-cp314-cp314-win_amd64.whl"


def _uv_bump(
    *new_filenames: str, base_filenames: tuple[str, ...] = ("requests-2.32.0-py3-none-any.whl",)
) -> _UvLockedVersion:
    return _UvLockedVersion(
        change=VersionChange(ecosystem="pypi", name="requests", old_version="2.32.0", new_version="2.33.0"),
        new_files=tuple(
            _LockedFile(url=f"{_PYPI_FILES}/{filename}", hash="sha256:abc")
            for filename in new_filenames or (_UNIVERSAL_WHEEL,)
        ),
        base_releases=(_BaseRelease(version="2.32.0", filenames=base_filenames),),
    )


_UV_BUMP = _uv_bump()


def _release(
    sha: str = "abc", uploaded: str = AGED, yanked: bool = False, filenames: tuple[str, ...] = (_UNIVERSAL_WHEEL,)
) -> dict[str, Any]:
    return {
        "info": {"yanked": yanked},
        "urls": [
            {
                "filename": filename,
                "url": f"{_PYPI_FILES}/{filename}",
                "digests": {"sha256": sha},
                "upload_time_iso_8601": uploaded,
            }
            for filename in filenames
        ],
    }


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
                "not a dependency",
            ),
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
            ("protocol_redirect", {"dependencies": {"left-pad": "npm:evil@1.0.0"}}, "version range"),
            ("tarball_redirect", {"dependencies": {"left-pad": "https://example.com/x.tgz"}}, "version range"),
            ("script_change", {"dependencies": {"left-pad": "^1.0.0"}, "scripts": {"postinstall": "curl"}}, "other"),
        ]
    )
    def test_package_json(self, _name: str, head: dict[str, Any], expected: str | None) -> None:
        base = {"name": "app", "dependencies": {"left-pad": "^1.0.0"}}
        problems = package_json_problems("package.json", json.dumps(base), json.dumps(head | {"name": "app"}))
        assert (problems == []) if expected is None else (expected in problems[0])

    @parameterized.expand(
        [
            ("specifier_bump", '"requests>=2.33"', '">=3.12"', None),
            ("direct_url", '"requests @ https://example.com/requests.whl"', '">=3.12"', "beyond its version"),
            ("requires_python", '"requests>=2.32"', '">=3.13"', "project fields"),
            ("new_dependency", '"requests>=2.32", "evil"', '">=3.12"', "adds or removes"),
        ]
    )
    def test_pyproject(self, _name: str, dependencies: str, requires_python: str, expected: str | None) -> None:
        def pyproject(deps: str, python: str) -> str:
            return f'[project]\nname = "app"\nrequires-python = {python}\ndependencies = [{deps}]\n'

        problems = pyproject_problems(
            "pyproject.toml", pyproject('"requests>=2.32"', '">=3.12"'), pyproject(dependencies, requires_python)
        )
        assert (problems == []) if expected is None else (expected in problems[0])

    @parameterized.expand(
        [
            (
                "pyproject_names_are_canonical",
                "pyproject.toml",
                '[project]\ndependencies = ["Django_Rest>=3.0", "requests>=2.32"]\n',
                '[project]\ndependencies = ["Django_Rest>=3.1", "requests>=2.32"]\n',
                ("pypi", {("django-rest", ">=3.1")}),
            ),
            (
                "pnpm_named_catalog",
                "pnpm-workspace.yaml",
                "catalogs:\n  react:\n    react: ^18.0.0\n    scheduler: ^0.23.0\n",
                "catalogs:\n  react:\n    react: ^18.3.0\n    scheduler: ^0.23.0\n",
                ("npm", {("react", "^18.3.0")}),
            ),
        ]
    )
    def test_manifest_changed_specifiers(
        self, _name: str, path: str, base: str, head: str, expected: tuple[str, set[tuple[str, str]]]
    ) -> None:
        assert manifest_changed_specifiers(path, base, head) == expected


class TestLockfileVersions(SimpleTestCase):
    @parameterized.expand(
        [
            ("patch", "1.2.3", "1.2.4", False),
            ("minor", "1.2.3", "1.3.0", False),
            ("major", "1.9.0", "2.0.0", True),
            ("zero_minor", "0.4.1", "0.5.0", True),
            ("zero_patch", "0.4.1", "0.4.2", False),
            ("calendar_major", "2024.10.1", "2025.1.0", True),
            ("not_numeric", "1.0.0", "next", True),
        ]
    )
    def test_is_major_update(self, _name: str, old: str, new: str, expected: bool) -> None:
        change = VersionChange(ecosystem="npm", name="left-pad", old_version=old, new_version=new)
        assert is_major_update(change) is expected

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

        locked, problems = pnpm_lock_versions("pnpm-lock.yaml", lock(base_versions), lock(head_versions))

        assert problems == []
        assert locked == [
            replace(
                _NPM_BUMP,
                change=replace(_NPM_BUMP.change, old_version=old, new_version=new),
                base_versions=tuple(base_versions),
            )
            for old, new in expected
        ]

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
        [("alias_the_base_locked", "web-vitals@6.2.1", None), ("new_alias", "lodash@4.17.21", "another package")]
    )
    def test_pnpm_new_snapshot_keeps_the_base_aliases(self, _name: str, reference: str, expected: str | None) -> None:
        def lock(left_pad: str, vitals: str) -> str:
            return _pnpm_lock(
                {
                    f"left-pad@{left_pad}": {"resolution": {"integrity": f"sha512-{left_pad}"}},
                    "web-vitals@6.2.1": {"resolution": {"integrity": "sha512-vitals"}},
                    "lodash@4.17.21": {"resolution": {"integrity": "sha512-lodash"}},
                },
                snapshots={f"left-pad@{left_pad}": {"dependencies": {"vitals": vitals}}},
            )

        _, problems = pnpm_lock_versions("pnpm-lock.yaml", lock("1.0.0", "web-vitals@6.2.1"), lock("1.1.0", reference))

        assert (problems == []) if expected is None else (expected in problems[0])

    def test_pnpm_refuses_an_override_change(self) -> None:
        packages = {"left-pad@1.0.0": {"resolution": {"integrity": "sha512-old"}}}
        _, problems = pnpm_lock_versions(
            "pnpm-lock.yaml", _pnpm_lock(packages), _pnpm_lock(packages, overrides={"left-pad": "npm:evil@1"})
        )
        assert "overrides" in problems[0]

    def test_uv_bump_yields_the_version_change(self) -> None:
        locked, problems = uv_lock_versions(
            "uv.lock",
            _uv_lock(_uv_package("requests", "2.32.0", "old")),
            _uv_lock(_uv_package("requests", "2.33.0", "abc")),
        )
        assert problems == []
        assert [v.change for v in locked] == [_UV_BUMP.change]

    @parameterized.expand(
        [
            ("new_transitive", _uv_package("evil", "1.0.0", "x"), "adds evil"),
            (
                "other_index",
                _uv_package("requests", "2.33.0", "x", '{ registry = "https://evil.example.com/simple" }'),
                "PyPI",
            ),
            ("same_version_new_hash", _uv_package("requests", "2.32.0", "swapped"), "changes requests 2.32.0 without"),
        ]
    )
    def test_uv_refuses(self, _name: str, head_package: str, expected: str) -> None:
        _, problems = uv_lock_versions(
            "uv.lock", _uv_lock(_uv_package("requests", "2.32.0", "old")), _uv_lock(head_package)
        )
        assert expected in problems[0]

    @parameterized.expand([("same_line", "1.27.0", None), ("locked_major", "2.0.0", "a major update")])
    def test_uv_retained_package_keeps_each_dependency_in_its_line(
        self, _name: str, urllib3_edge: str, expected: str | None
    ) -> None:
        def lock(edge: str, urllib3_versions: tuple[str, ...]) -> str:
            dependencies = f'{{ name = "urllib3", version = "{edge}" }}'
            return _uv_lock(
                _uv_package("requests", "2.32.0", "old", dependencies=dependencies),
                *(_uv_package("urllib3", version, version) for version in urllib3_versions),
            )

        _, problems = uv_lock_versions(
            "uv.lock", lock("1.26.0", ("1.26.0", "2.0.0")), lock(urllib3_edge, ("1.27.0", "2.0.0"))
        )

        assert (problems == []) if expected is None else (expected in problems[0])


class TestRegistryProblems(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "clean",
                _packument(
                    {"attestations": _PROVENANCE}, {"dist": {"integrity": "sha512-new", "attestations": _PROVENANCE}}
                ),
                None,
            ),
            ("too_new", _packument({}, {"dist": {"integrity": "sha512-new"}}, published=FRESH), "less than 7 days"),
            ("hash_mismatch", _packument({}, {"dist": {"integrity": "sha512-other"}}), "does not match"),
            (
                "lost_provenance",
                _packument({"attestations": _PROVENANCE}, {"dist": {"integrity": "sha512-new"}}),
                "no provenance",
            ),
            (
                "new_install_script",
                _packument({}, {"dist": {"integrity": "sha512-new"}, "scripts": {"postinstall": "node x.js"}}),
                "install script",
            ),
            ("unlisted_version", {"time": {}, "versions": {}}, "does not list"),
            param(
                "provenance_of_another_locked_version",
                {
                    **_packument({}, {"dist": {"integrity": "sha512-new"}}),
                    "versions": {
                        "0.9.0": {"dist": {"attestations": _PROVENANCE}},
                        "1.0.0": {"dist": {}},
                        "1.1.0": {"dist": {"integrity": "sha512-new"}},
                    },
                },
                "no provenance",
                locked=replace(_NPM_BUMP, base_versions=("0.9.0", "1.0.0")),
            ),
        ]
    )
    def test_npm(
        self, _name: str, packument: dict[str, Any], expected: str | None, locked: _NpmLockedVersion = _NPM_BUMP
    ) -> None:
        problems = npm_registry_problems(locked, packument, NOW)
        assert (problems == []) if expected is None else (expected in problems[0])

    def test_a_registry_error_raises_so_the_activity_retries_instead_of_refusing(self) -> None:
        def respond(status: int) -> requests.Response:
            response = requests.Response()
            response.status_code = status
            return response

        with patch(f"{_VERIFIER}.npm_registry_request", return_value=respond(404)):
            assert default_registry_readers().npm_packument("left-pad") is None
        with patch(f"{_VERIFIER}.npm_registry_request", return_value=respond(503)), self.assertRaises(HTTPError):
            default_registry_readers().npm_packument("left-pad")

    @parameterized.expand(
        [
            ("clean", _release(), True, True, None),
            ("hash_mismatch", _release(sha="other"), True, True, "does not match"),
            ("too_new", _release(uploaded=FRESH), True, True, "less than 7 days"),
            ("yanked", _release(yanked=True), True, True, "yanked"),
            ("lost_provenance", _release(), True, False, "no provenance"),
            param("no_locked_files", _release(), True, True, "lists no files", locked=replace(_UV_BUMP, new_files=())),
            param(
                "foreign_download_host",
                _release(),
                True,
                True,
                "URL",
                locked=replace(
                    _UV_BUMP, new_files=(_LockedFile(url=f"http://localhost/{_UNIVERSAL_WHEEL}", hash="sha256:abc"),)
                ),
            ),
            param(
                "loses_the_linux_wheel",
                _release(filenames=(_WINDOWS_WHEEL, "requests-2.33.0.tar.gz")),
                True,
                True,
                "no wheel for linux, macos",
                locked=_uv_bump(_WINDOWS_WHEEL, "requests-2.33.0.tar.gz"),
            ),
            param(
                "manylinux_tag_moves",
                _release(filenames=(_LINUX_WHEEL,)),
                True,
                True,
                None,
                locked=_uv_bump(
                    _LINUX_WHEEL,
                    base_filenames=("requests-2.32.0-cp313-cp313-manylinux2014_x86_64.whl",),
                ),
            ),
        ]
    )
    def test_pypi(
        self,
        _name: str,
        release: dict[str, Any],
        old: bool,
        new: bool,
        expected: str | None,
        locked: _UvLockedVersion = _UV_BUMP,
    ) -> None:
        problems = pypi_registry_problems(locked, release, old, new, NOW)
        assert (problems == []) if expected is None else (expected in problems[0])

    @parameterized.expand(
        [
            ("every_new_file_has_it", {_LINUX_WHEEL, _WINDOWS_WHEEL}, set(), None),
            ("one_new_file_lost_it", {_WINDOWS_WHEEL}, {"2.32.0"}, "no provenance on every file"),
            ("another_base_version_had_it", set(), {"1.0.0"}, "no provenance on every file"),
            ("no_version_ever_had_it", set(), set(), None),
        ]
    )
    def test_pypi_provenance_covers_every_new_file_and_every_base_version(
        self, _name: str, new_with_provenance: set[str], base_with_provenance: set[str], expected: str | None
    ) -> None:
        locked = replace(
            _uv_bump(_LINUX_WHEEL, _WINDOWS_WHEEL),
            base_releases=tuple(
                _BaseRelease(version=version, filenames=(f"requests-{version}-cp313-cp313-manylinux2014_x86_64.whl",))
                for version in ("1.0.0", "2.32.0")
            ),
        )

        def has_provenance(_name: str, version: str, filename: str) -> bool:
            return filename in new_with_provenance if version == "2.33.0" else version in base_with_provenance

        readers = RegistryReaders(
            npm_packument=lambda _name: None,
            pypi_release=lambda _name, _version: _release(filenames=(_LINUX_WHEEL, _WINDOWS_WHEEL)),
            pypi_has_provenance=has_provenance,
        )

        problems = _registry_problems([], [locked], readers, NOW)

        assert (problems == []) if expected is None else (expected in problems[-1])


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
        }
        readers = RegistryReaders(
            npm_packument=lambda _name: _packument({}, {"dist": {"integrity": "sha512-new"}}),
            pypi_release=lambda _name, _version: None,
            pypi_has_provenance=lambda _name, _version, _filename: False,
        )

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
            now=NOW,
            readers=readers,
        )

        assert result.problems == expected_problems
        assert result.verified is (not expected_problems)
        assert result.changes == (_NPM_BUMP.change,)
        assert result.cleared_paths == (() if expected_problems else ("pnpm-lock.yaml",))

    @parameterized.expand([("admits_the_locked_version", ">=2.33", False), ("names_another_major", ">=3", True)])
    def test_a_python_specifier_must_admit_a_newly_locked_version(
        self, _name: str, head_specifier: str, refused: bool
    ) -> None:
        files = {
            ("pyproject.toml", "base"): '[project]\ndependencies = ["requests>=2.32"]\n',
            ("pyproject.toml", HEAD): f'[project]\ndependencies = ["requests{head_specifier}"]\n',
            ("uv.lock", "base"): _uv_lock(_uv_package("requests", "2.32.0", "old")),
            ("uv.lock", HEAD): _uv_lock(_uv_package("requests", "2.33.0", "abc")),
        }

        result = verify_renovate_update(
            pr=_renovate_pr(),
            repo=REPO,
            commits=[_commit()],
            files=[{"filename": path, "status": "modified"} for path in ("pyproject.toml", "uv.lock")],
            merge_base_sha="base",
            head_sha=HEAD,
            read_file=lambda path, ref: files.get((path, ref)),
            now=NOW,
            readers=RegistryReaders(
                npm_packument=lambda _name: None,
                pypi_release=lambda _name, _version: None,
                pypi_has_provenance=lambda _name, _version, _filename: False,
            ),
        )

        assert (
            "pyproject.toml sets requests to >=3, which no newly locked version meets." in result.problems
        ) is refused
