import pytest

from products.engineering_analytics.backend.facade import api
from products.engineering_analytics.backend.tests._github_fixtures import _depot_attempt_row
from products.engineering_analytics.backend.tests._logic_helpers import _WarehouseMixin


def _attempt(attempt_id: str, started_at: str, finished_at: str, **overrides: object) -> dict:
    return _depot_attempt_row(
        attempt_id=attempt_id, attempt_started_at=started_at, attempt_finished_at=finished_at, **overrides
    )


class TestDepotCIUsage(_WarehouseMixin):
    def test_sums_finished_attempts_of_the_source_repository_in_the_window(self) -> None:
        self._create_depot_table(
            [
                _attempt("aaaaaaaaaa", "2026-10-27T10:00:00Z", "2026-10-27T10:10:00Z"),
                # The curated CI reads drop this hand-off job, but Depot bills it.
                _attempt(
                    "bbbbbbbbbb",
                    "2026-10-28T10:00:00.500Z",
                    "2026-10-28T10:05:00Z",
                    job_key="backend:wait-for-handoff",
                ),
                _attempt("cccccccccc", "2026-10-29T10:00:00Z", ""),
                _attempt("dddddddddd", "2026-10-25T23:59:00Z", "2026-10-26T00:30:00Z"),
                _attempt("eeeeeeeeee", "2026-11-02T00:00:00Z", "2026-11-02T00:30:00Z"),
                _attempt("ffffffffff", "2026-10-27T10:00:00Z", "2026-10-27T11:00:00Z", repo="PostHog/other"),
            ]
        )

        [usage] = api.get_depot_ci_usage(
            team=self.team, date_from="2026-10-26T00:00:00Z", date_to="2026-11-02T00:00:00Z"
        )

        assert (usage.repo, usage.elapsed_seconds) == ("posthog/posthog", 899.5)
        assert usage.estimated_cost_usd == pytest.approx(899.5 * 2 * 0.00005)

    def test_is_empty_without_a_depot_source(self) -> None:
        assert api.get_depot_ci_usage(team=self.team) == []
