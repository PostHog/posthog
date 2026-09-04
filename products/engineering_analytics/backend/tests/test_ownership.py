from collections.abc import Iterator
from dataclasses import field
from time import monotonic, sleep

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.dataclasses import frozen

from products.engineering_analytics.backend.facade.contracts import UNOWNED_TEAM
from products.engineering_analytics.backend.logic.ownership import (
    _MAX_FILE_BYTES,
    UNPLACED,
    GitHubRepoFiles,
    OwnershipUnavailable,
    PlacedTest,
    QuarantinedTestFile,
    resolve_test_ownership,
)

_OWNERS = {
    "owners.yaml": "version: 1\nowners: [team-root]\n",
    "nodejs/src/owners.yaml": "version: 1\nowners: [team-ingestion]\n",
    "frontend/src/scenes/owners.yaml": "version: 1\nowners: [team-product-analytics]\n",
    "rust/owners.yaml": "version: 1\nowners: [team-rust]\n",
    "rust/common/kafka/owners.yaml": "version: 1\nowners: ['@someone', team-streams]\n",
}

_TRACKED = {
    "nodejs/src/cdp/cdp-e2e.serial.test.ts",
    "frontend/src/scenes/insights/SQLBoxPlot.stories.tsx",
    "products/product_analytics/backend/tests/test_insight.py",
    "rust/personhog-coordination/Cargo.toml",
    "rust/common/kafka/Cargo.toml",
}


@frozen(frozen=False)
class _FakeRepoFiles:
    owners: dict[str, str] = field(default_factory=lambda: dict(_OWNERS))
    tracked: set[str] = field(default_factory=lambda: set(_TRACKED))

    def read(self, path: str) -> str | None:
        return self.owners.get(path)

    def exists_all(self, paths: list[str]) -> dict[str, bool]:
        return {path: path in self.tracked for path in paths}

    def read_all(self, paths: list[str]) -> None:
        pass


def _placements(files: _FakeRepoFiles) -> list[PlacedTest]:
    return resolve_test_ownership(
        "PostHog/posthog",
        [
            QuarantinedTestFile(source_path="src/cdp/cdp-e2e.serial.test.ts", crate=""),
            QuarantinedTestFile(source_path="", crate="personhog-coordination"),
        ],
        files=files,
    ).tests


class TestRepoOwnership(SimpleTestCase):
    @parameterized.expand(
        [
            # nodejs and frontend suites both report 'src/...', so placing by the reported path
            # alone hands one team's test to the other.
            ("src/cdp/cdp-e2e.serial.test.ts", "", "nodejs/src/cdp/cdp-e2e.serial.test.ts", "team-ingestion"),
            (
                "../../frontend/src/scenes/insights/SQLBoxPlot.stories.tsx",
                "",
                "frontend/src/scenes/insights/SQLBoxPlot.stories.tsx",
                "team-product-analytics",
            ),
            (
                "products/product_analytics/backend/tests/test_insight.py",
                "",
                "products/product_analytics/backend/tests/test_insight.py",
                "team-root",
            ),
            # A crate is placed by its manifest, which is not the test's file, so nothing to link to.
            ("", "personhog-coordination", "", "team-rust"),
            # Cargo's crate name is not its directory, and '@handle' owners are people, not teams.
            ("", "common-kafka", "", "team-streams"),
            ("feature-flags", "", "", UNOWNED_TEAM),
            ("src/gone/deleted.test.ts", "", "", UNOWNED_TEAM),
        ]
    )
    def test_places_a_test_and_names_its_owner(self, source_path: str, crate: str, path: str, owner: str) -> None:
        [placed] = resolve_test_ownership(
            "PostHog/posthog", [QuarantinedTestFile(source_path=source_path, crate=crate)], files=_FakeRepoFiles()
        ).tests
        assert placed.path == path
        assert placed.owner_team == owner

    def test_a_failed_read_leaves_the_whole_batch_unowned(self) -> None:
        class _Failing(_FakeRepoFiles):
            def read(self, path: str) -> str | None:
                raise OwnershipUnavailable("boom")

        assert _placements(_Failing()) == [UNPLACED, UNPLACED]

    def test_a_repository_missing_its_root_file_attributes_nothing(self) -> None:
        # A private or renamed repo answers 404 to every path. Without the root-file guard the
        # nested files this fake still serves would attribute part of the board.
        no_root = _FakeRepoFiles(owners={k: v for k, v in _OWNERS.items() if k != "owners.yaml"})
        assert _placements(no_root) == [UNPLACED, UNPLACED]

    def test_a_resolved_batch_says_so(self) -> None:
        assert resolve_test_ownership("PostHog/posthog", [], files=_FakeRepoFiles()).resolved


class TestGitHubRepoFiles(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand([(500,), (403,)])
    def test_an_unexpected_status_raises_rather_than_reading_as_absent(self, status: int) -> None:
        # Reading a failure as "no such file" reattributes everything under it to an ancestor.
        with patch(
            "products.engineering_analytics.backend.logic.ownership.github_request",
            return_value=_response(status),
        ):
            with self.assertRaises(OwnershipUnavailable):
                GitHubRepoFiles("PostHog/posthog").read("owners.yaml")

    def test_a_missing_file_is_absent_and_fetched_once(self) -> None:
        with patch(
            "products.engineering_analytics.backend.logic.ownership.github_request",
            return_value=_response(404),
        ) as request:
            files = GitHubRepoFiles("PostHog/posthog")
            assert files.read("nodejs/owners.yaml") is None
            assert files.read("nodejs/owners.yaml") is None
            assert GitHubRepoFiles("PostHog/posthog").read("nodejs/owners.yaml") is None
        assert request.call_count == 1

    def test_a_slow_repository_gives_up_instead_of_holding_the_worker(self) -> None:
        # A cold board asks for hundreds of files. Without a budget for the whole resolution, a
        # stalled raw host holds a web worker far past the per-request timeout.
        def never_returns(_method: str, _url: str, **_kwargs: object) -> object:
            sleep(2)
            raise AssertionError("unreachable")

        with patch("products.engineering_analytics.backend.logic.ownership.github_request", side_effect=never_returns):
            files = GitHubRepoFiles("PostHog/posthog")
            files._deadline = monotonic()
            with self.assertRaises(OwnershipUnavailable):
                files.read("owners.yaml")

    @parameterized.expand([("declared", True), ("streamed", False)])
    def test_an_oversized_file_is_refused(self, _name: str, declare_length: bool) -> None:
        # A connected repository controls these files, so an unbounded read would put its bytes in
        # a worker's memory and in Redis. Content-Length can lie, so the streamed read is the ceiling.
        oversized = b"x" * (_MAX_FILE_BYTES + 1)
        headers = {"Content-Length": str(len(oversized))} if declare_length else {}
        with patch(
            "products.engineering_analytics.backend.logic.ownership.github_request",
            return_value=_response(200, body=oversized, headers=headers),
        ):
            with self.assertRaises(OwnershipUnavailable):
                GitHubRepoFiles("PostHog/posthog").read("owners.yaml")


class _response:
    encoding = "utf-8"

    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._body = body

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for start in range(0, len(self._body), chunk_size):
            yield self._body[start : start + chunk_size]

    def __enter__(self) -> "_response":
        return self

    def __exit__(self, *args: object) -> None:
        pass
