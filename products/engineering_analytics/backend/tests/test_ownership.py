from types import SimpleNamespace

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.engineering_analytics.backend.logic.ownership import (
    UNPLACED,
    GitHubRepoFiles,
    OwnershipUnavailable,
    QuarantinedTestFile,
    RepoOwnership,
)

_OWNERS = {
    "owners.yaml": "version: 1\nowners: [team-root]\n",
    "nodejs/src/owners.yaml": "version: 1\nowners: [team-ingestion]\n",
    "frontend/src/scenes/owners.yaml": "version: 1\nowners: [team-product-analytics]\n",
    "rust/owners.yaml": "version: 1\nowners: [team-rust]\n",
}

_TRACKED = {
    *_OWNERS,
    "nodejs/src/cdp/cdp-e2e.serial.test.ts",
    "frontend/src/scenes/insights/SQLBoxPlot.stories.tsx",
    "products/product_analytics/backend/tests/test_insight.py",
    "rust/personhog-coordination/Cargo.toml",
}


class _FakeRepoFiles:
    def read(self, path: str) -> str | None:
        return _OWNERS.get(path)

    def exists(self, path: str) -> bool:
        return path in _TRACKED


class TestRepoOwnership(SimpleTestCase):
    @parameterized.expand(
        [
            # nodejs and frontend suites both report 'src/...', so placing by the reported path
            # alone hands one team's test to the other.
            ("jest", "src/cdp/cdp-e2e.serial.test.ts", "", "nodejs/src/cdp/cdp-e2e.serial.test.ts", "team-ingestion"),
            (
                "storybook",
                "",
                "../../frontend/src/scenes/insights/SQLBoxPlot.stories.tsx",
                "frontend/src/scenes/insights/SQLBoxPlot.stories.tsx",
                "team-product-analytics",
            ),
            (
                "rust",
                "",
                "personhog-coordination::k3s_integration",
                "rust/personhog-coordination/Cargo.toml",
                "team-rust",
            ),
            (
                "pytest",
                "products/product_analytics/backend/tests/test_insight.py",
                "pytest",
                "products/product_analytics/backend/tests/test_insight.py",
                "team-root",
            ),
            ("jest", "", "feature-flags", None, None),
            ("jest", "src/gone/deleted.test.ts", "", None, None),
        ]
    )
    def test_places_a_test_and_names_its_owner(
        self, runner: str, file: str, parent: str, path: str | None, owner: str | None
    ) -> None:
        ownership = RepoOwnership("PostHog/posthog", files=_FakeRepoFiles())
        [placed] = ownership.for_tests([QuarantinedTestFile(runner=runner, file=file, parent=parent)])
        assert placed.path == path
        assert placed.owner_team == owner

    def test_an_unreadable_repository_leaves_the_whole_batch_unowned(self) -> None:
        class _Failing(_FakeRepoFiles):
            def exists(self, path: str) -> bool:
                raise OwnershipUnavailable("boom")

        ownership = RepoOwnership("PostHog/posthog", files=_Failing())
        tests = [
            QuarantinedTestFile(runner="jest", file="src/cdp/cdp-e2e.serial.test.ts", parent=""),
            QuarantinedTestFile(runner="rust", file="", parent="personhog-coordination::k3s_integration"),
        ]
        assert ownership.for_tests(tests) == [UNPLACED, UNPLACED]


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
                GitHubRepoFiles(repository="PostHog/posthog").read("owners.yaml")

    def test_a_missing_file_is_absent_and_cached(self) -> None:
        with patch(
            "products.engineering_analytics.backend.logic.ownership.github_request",
            return_value=_response(404),
        ) as request:
            files = GitHubRepoFiles(repository="PostHog/posthog")
            assert files.read("nodejs/owners.yaml") is None
            assert files.read("nodejs/owners.yaml") is None
        assert request.call_count == 1


def _response(status: int, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(status_code=status, text=text)
