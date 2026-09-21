import json
import struct
from datetime import UTC, datetime, timedelta

import time_machine

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

import zstd
import requests
from parameterized import parameterized
from requests.structures import CaseInsensitiveDict

from products.error_tracking.backend.logic.source_links import (
    GitProvider,
    Repository,
    RepositoryTree,
    SourcePath,
    SourceTarget,
    github_tree,
    match_sources,
    parse_repository,
    parse_source,
    read_source_map,
    source_map_sources,
)

_MAGIC = b"posthog_error_tracking"

REPOSITORY = Repository(provider="github", host="github.com", owner="acme", name="app")
COMMIT = "0123456789abcdef0123456789abcdef01234567"
APPS_SHA = "a" * 40
SERVICES_SHA = "b" * 40
TOOLS_SHA = "c" * 40
TREES = "/repos/acme/app/git/trees"


def _json_response(status: int, body: dict | None = None, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.models.Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict(headers or {})
    response._content = json.dumps(body or {}).encode()
    return response


class _ScriptedGitHubApi:
    """Replays the queued responses of each request path and records the ETag each request sent.
    A path without a queue gets no response, which is how a failed request looks to the resolver."""

    def __init__(self, responses: dict[str, list[requests.Response]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str | None]] = []

    def get(self, path: str, *, endpoint: str, etag: str | None = None) -> requests.Response | None:
        self.calls.append((path, etag))
        queue = self.responses.get(path)
        if not queue:
            return None
        return queue.pop(0) if len(queue) > 1 else queue[0]


def _truncated_repository(*, with_tools: bool) -> dict[str, list[requests.Response]]:
    responses = {
        f"{TREES}/{COMMIT}?recursive=1": [
            _json_response(
                200,
                {
                    "truncated": True,
                    "tree": [
                        {"path": "apps", "type": "tree", "sha": APPS_SHA},
                        {"path": "apps/web/src/a.ts", "type": "blob"},
                        {"path": "services", "type": "tree", "sha": SERVICES_SHA},
                        {"path": "services/api/x.ts", "type": "blob"},
                    ],
                },
            )
        ],
        f"{TREES}/{COMMIT}": [
            _json_response(
                200,
                {
                    "truncated": False,
                    "tree": [
                        {"path": "apps", "type": "tree", "sha": APPS_SHA},
                        {"path": "services", "type": "tree", "sha": SERVICES_SHA},
                        {"path": "tools", "type": "tree", "sha": TOOLS_SHA},
                        {"path": "turbo.json", "type": "blob"},
                    ],
                },
            )
        ],
        f"{TREES}/{SERVICES_SHA}?recursive=1": [
            _json_response(
                200,
                {
                    "truncated": False,
                    "tree": [{"path": "api/x.ts", "type": "blob"}, {"path": "worker/y.ts", "type": "blob"}],
                },
            )
        ],
    }
    if with_tools:
        responses[f"{TREES}/{TOOLS_SHA}?recursive=1"] = [
            _json_response(200, {"truncated": False, "tree": [{"path": "cli/z.ts", "type": "blob"}]})
        ]
    return responses


def _container(source: bytes, source_map: bytes, *, version: int = 2, compressed: bool = True) -> bytes:
    payload = struct.pack("<Q", len(source)) + source + struct.pack("<Q", len(source_map)) + source_map
    header = _MAGIC + struct.pack("<II", version, 2)
    if version == 1:
        return header + payload
    if compressed:
        return header + bytes([1]) + zstd.compress(payload)
    return header + bytes([0]) + payload


class TestSourceLinks(SimpleTestCase):
    @parameterized.expand(
        [
            ("esbuild_relative_to_map", "../src/a.ts", SourcePath(hops=1, segments=("src", "a.ts"))),
            ("webpack_context_relative", "./src/a.ts", SourcePath(hops=0, segments=("src", "a.ts"))),
            ("webpack_namespace", "webpack://_N_E/./app/page.tsx", SourcePath(hops=0, segments=("app", "page.tsx"))),
            ("webpack_without_namespace", "webpack:///./src/a.ts", SourcePath(hops=0, segments=("src", "a.ts"))),
            (
                "webpack_hops_and_query",
                "webpack://app/../../packages/x/src/a.ts?abc",
                SourcePath(hops=2, segments=("packages", "x", "src", "a.ts")),
            ),
            (
                "file_url",
                "file:///Users/me/proj/src/a.ts",
                SourcePath(hops=0, segments=("Users", "me", "proj", "src", "a.ts")),
            ),
            ("inner_parent_segment", "src/../lib/b.ts", SourcePath(hops=0, segments=("lib", "b.ts"))),
            ("windows_separators", "C:\\proj\\src\\a.ts", SourcePath(hops=0, segments=("C:", "proj", "src", "a.ts"))),
            ("webpack_runtime", "webpack://app/webpack/runtime/x", None),
            ("dependency", "../node_modules/foo/index.js", None),
            ("anonymous", "<anonymous>", None),
            ("empty", "", None),
        ]
    )
    def test_parse_source(self, _name: str, raw: str, expected: SourcePath | None) -> None:
        assert parse_source(raw) == expected

    @parameterized.expand(
        [
            ("scp_remote", "git@github.com:PostHog/posthog.git", ("github", "PostHog", "posthog")),
            ("https_remote", "https://github.com/PostHog/posthog", ("github", "PostHog", "posthog")),
            ("ssh_remote", "ssh://git@github.com/PostHog/posthog.git", ("github", "PostHog", "posthog")),
            ("bare_path", "PostHog/posthog", ("github", "PostHog", "posthog")),
            ("gitlab_subgroup", "https://gitlab.com/group/sub/repo.git", ("gitlab", "group/sub", "repo")),
            ("github_extra_segments", "https://github.com/PostHog/posthog/tree/main", None),
            ("unsupported_host", "https://bitbucket.org/a/b", None),
            ("traversal", "https://github.com/../x", None),
            ("empty", "", None),
        ]
    )
    def test_parse_repository(self, _name: str, value: str, expected: tuple[GitProvider, str, str] | None) -> None:
        repository = parse_repository(value)
        if expected is None:
            assert repository is None
        else:
            provider, owner, name = expected
            assert repository == Repository(provider=provider, host=f"{provider}.com", owner=owner, name=name)

    def test_match_sources_places_a_single_package_at_the_root(self) -> None:
        tree = RepositoryTree(["src/a.ts", "src/b.ts", "README.md"])
        assert match_sources(tree, ["../src/a.ts", "../src/b.ts", "../src/missing.ts"]) == {
            "../src/a.ts": "src/a.ts",
            "../src/b.ts": "src/b.ts",
        }

    def test_match_sources_picks_the_package_that_holds_the_most_sources(self) -> None:
        tree = RepositoryTree(
            [
                "packages/web/src/index.ts",
                "packages/web/src/only-web.ts",
                "packages/api/src/index.ts",
                "packages/api/src/only-api.ts",
            ]
        )
        assert match_sources(tree, ["../src/index.ts", "../src/only-api.ts"]) == {
            "../src/index.ts": "packages/api/src/index.ts",
            "../src/only-api.ts": "packages/api/src/only-api.ts",
        }

    def test_match_sources_places_deeper_hops_relative_to_the_same_anchor(self) -> None:
        tree = RepositoryTree(["packages/web/src/index.ts", "packages/shared/src/util.ts", "shared/src/util.ts"])
        assert match_sources(tree, ["../src/index.ts", "../../shared/src/util.ts"]) == {
            "../src/index.ts": "packages/web/src/index.ts",
            "../../shared/src/util.ts": "packages/shared/src/util.ts",
        }

    def test_match_sources_drops_build_machine_directories_from_absolute_paths(self) -> None:
        tree = RepositoryTree(["src/a.ts", "docs/a.md"])
        assert match_sources(tree, ["/home/ci/app/src/a.ts"]) == {"/home/ci/app/src/a.ts": "src/a.ts"}

    def test_match_sources_leaves_an_ambiguous_suffix_unlinked(self) -> None:
        tree = RepositoryTree(["packages/web/src/a.ts", "packages/api/src/a.ts"])
        assert match_sources(tree, ["/home/ci/build/a.ts"]) == {}

    def test_match_sources_ignores_virtual_sources(self) -> None:
        tree = RepositoryTree(["src/a.ts"])
        assert match_sources(tree, ["webpack://app/webpack/runtime/x", "webpack://app/./src/a.ts"]) == {
            "webpack://app/./src/a.ts": "src/a.ts"
        }

    @parameterized.expand(
        [
            ("v2_zstd", 2, True),
            ("v2_uncompressed", 2, False),
            ("v1", 1, False),
        ]
    )
    def test_read_source_map_reads_every_container_version(self, _name: str, version: int, compressed: bool) -> None:
        source_map = json.dumps({"version": 3, "sources": ["../src/a.ts"], "mappings": ""}).encode()
        data = _container(b"console.log(1)", source_map, version=version, compressed=compressed)
        assert read_source_map(data) == source_map.decode()

    def test_read_source_map_rejects_other_symbol_data(self) -> None:
        data = _MAGIC + struct.pack("<II", 2, 4) + bytes([0]) + b"proguard"
        with self.assertRaises(ValueError):
            read_source_map(data)

    def test_source_map_sources_applies_source_root_like_the_resolver(self) -> None:
        source_map = json.dumps({"sources": ["a.ts", "/abs.ts", "webpack://x/b.ts"], "sourceRoot": "src/"})
        assert source_map_sources(source_map) == ["src/a.ts", "/abs.ts", "webpack://x/b.ts"]


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "source-links-tree"}}
)
class TestGitHubTree(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    def test_reads_the_directories_github_left_out_of_a_truncated_response(self) -> None:
        api = _ScriptedGitHubApi(_truncated_repository(with_tools=True))

        tree = github_tree(api, SourceTarget(repository=REPOSITORY, ref=COMMIT, pinned=True))

        assert tree is not None
        assert tree.paths == {
            "apps/web/src/a.ts",
            "services/api/x.ts",
            "services/worker/y.ts",
            "tools/cli/z.ts",
            "turbo.json",
        }
        # "apps" sorts before the cut, so it is not read a second time.
        assert [path for path, _ in api.calls] == [
            f"{TREES}/{COMMIT}?recursive=1",
            f"{TREES}/{COMMIT}",
            f"{TREES}/{SERVICES_SHA}?recursive=1",
            f"{TREES}/{TOOLS_SHA}?recursive=1",
        ]

    def test_a_failed_tail_request_does_not_pass_a_partial_tree_off_as_the_repository(self) -> None:
        # A commit tree is kept for a week, so a partial one would hide the tail's links that long.
        api = _ScriptedGitHubApi(_truncated_repository(with_tools=False))

        assert github_tree(api, SourceTarget(repository=REPOSITORY, ref=COMMIT, pinned=True)) is None

    def test_revalidates_a_branch_tree_with_its_etag_instead_of_downloading_it_again(self) -> None:
        path = f"{TREES}/main?recursive=1"
        api = _ScriptedGitHubApi(
            {
                path: [
                    _json_response(
                        200, {"truncated": False, "tree": [{"path": "src/a.ts", "type": "blob"}]}, {"ETag": 'W/"v1"'}
                    ),
                    _json_response(304),
                ]
            }
        )
        target = SourceTarget(repository=REPOSITORY, ref="main", pinned=False)

        with time_machine.travel(datetime(2026, 1, 1, tzinfo=UTC), tick=False) as traveller:
            first = github_tree(api, target)
            traveller.shift(timedelta(hours=2))
            second = github_tree(api, target)
            third = github_tree(api, target)

        assert first is not None and second is not None and third is not None
        assert first.paths == second.paths == third.paths == {"src/a.ts"}
        # The third read is inside the trusted hour, so it sends nothing.
        assert api.calls == [(path, None), (path, 'W/"v1"')]
