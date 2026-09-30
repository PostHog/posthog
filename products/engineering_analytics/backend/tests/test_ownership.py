from dataclasses import field

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.dataclasses import frozen
from posthog.ownership.paths import UNOWNED_TEAM
from posthog.ownership.repo_files import OwnershipUnavailable

from products.engineering_analytics.backend.logic.ownership import (
    UNPLACED,
    PlacedTest,
    QuarantinedTestFile,
    resolve_test_ownership,
)

_ROOT_OWNERS = """version: 1
owners: [team-root]
teams:
  team-ingestion:
    notifications: '#alerts-ingestion'
"""

_OWNERS = {
    "owners.yaml": _ROOT_OWNERS,
    "services/mcp/tests/owners.yaml": "version: 1\nowners: [mcp-analytics]\n",
    "nodejs/src/owners.yaml": "version: 1\nowners: [team-ingestion]\n",
    "frontend/src/scenes/owners.yaml": "version: 1\nowners: [team-product-analytics]\n",
    "rust/owners.yaml": "version: 1\nowners: [team-rust]\n",
    "rust/common/kafka/owners.yaml": "version: 1\nowners: ['@someone', team-streams]\n",
}

_TRACKED = {
    "services/mcp/tests/tools/projects.integration.test.ts",
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
            (
                "tests/tools/projects.integration.test.ts",
                "",
                "services/mcp/tests/tools/projects.integration.test.ts",
                "mcp-analytics",
            ),
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
