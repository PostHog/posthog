from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import InvalidationResult
from products.analytics_platform.backend.models import PreaggregationJob
from products.marketing_analytics.backend.services.cost_precompute_invalidation import CostInvalidation

_API = "products.marketing_analytics.backend.api"
_INVALIDATE = f"{_API}.invalidate_cost_precompute"
_REBUILD_TASK = f"{_API}.rebuild_marketing_cost_precompute"
_SERVICE = "products.marketing_analytics.backend.services.cost_precompute_invalidation"


def _invalidation(jobs_deleted=3, hashes=3, sources=1, start=None, end=None):
    return CostInvalidation(
        sources_resolved=sources,
        query_hashes_resolved=hashes,
        result=InvalidationResult(jobs_deleted=jobs_deleted, effective_start=start, effective_end=end),
    )


class CostPrecomputeInvalidateAPITest(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.pk}/marketing_analytics/cost_precompute/invalidate/"

    def _post(self, **body):
        payload = {"date_from": "2026-07-16", "date_to": "2026-07-18", **body}
        return self.client.post(self._url(), payload, format="json")

    # --- Routing and validation ---

    def test_route_exists_and_invalidates(self):
        with patch(_INVALIDATE, return_value=_invalidation()) as invalidate, patch(_REBUILD_TASK):
            response = self._post()

        assert response.status_code == status.HTTP_202_ACCEPTED, response.json()
        assert response.json()["jobs_invalidated"] == 3
        assert invalidate.call_args.args[0] == self.team

    def test_rejects_inverted_range(self):
        response = self._post(date_from="2026-07-18", date_to="2026-07-16")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "date_to" in response.json()

    def test_rejects_a_range_wider_than_the_cap(self):
        response = self._post(date_from="2020-01-01", date_to="2026-07-18")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "at most" in str(response.json())

    def test_requires_both_dates(self):
        response = self.client.post(self._url(), {"date_from": "2026-07-16"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_single_day_range_is_allowed(self):
        with patch(_INVALIDATE, return_value=_invalidation()) as invalidate, patch(_REBUILD_TASK):
            response = self._post(date_from="2026-07-16", date_to="2026-07-16")

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert invalidate.call_args.args[1] == invalidate.call_args.args[2]

    # --- Rebuild scheduling ---

    def test_schedules_a_rebuild_by_default(self):
        with patch(_INVALIDATE, return_value=_invalidation()), patch(_REBUILD_TASK) as task:
            response = self._post()

        assert response.json()["rebuild"]["scheduled"] is True
        task.delay.assert_called_once()
        assert task.delay.call_args.args[0] == self.team.pk

    def test_rebuild_can_be_declined(self):
        with patch(_INVALIDATE, return_value=_invalidation()), patch(_REBUILD_TASK) as task:
            response = self._post(rebuild=False)

        assert response.json()["rebuild"]["scheduled"] is False
        task.delay.assert_not_called()
        assert any("next read" in note for note in response.json()["notes"])

    def test_no_rebuild_when_nothing_was_invalidated(self):
        """Rebuilding would only re-confirm windows that are still covered."""
        with patch(_INVALIDATE, return_value=_invalidation(jobs_deleted=0)), patch(_REBUILD_TASK) as task:
            response = self._post()

        assert response.json()["rebuild"]["scheduled"] is False
        task.delay.assert_not_called()

    def test_rebuild_window_is_clamped_to_the_warmed_window(self):
        # Asking to rebuild 2024 shouldn't queue work for rows nothing keeps warm.
        with (
            patch(_INVALIDATE, return_value=_invalidation()),
            patch(_REBUILD_TASK) as task,
            patch(f"{_API}.REBUILD_MAX_WINDOW_DAYS", 90),
        ):
            response = self._post(date_from="2024-01-01", date_to="2026-07-18")

        window = response.json()["rebuild"]["window"]
        assert window["date_from"] > "2024-01-01"
        assert task.delay.call_args.args[1] == window["date_from"]

    # --- Dry run ---

    def test_dry_run_returns_200_and_schedules_nothing(self):
        with patch(_INVALIDATE, return_value=_invalidation()) as invalidate, patch(_REBUILD_TASK) as task:
            response = self._post(dry_run=True)

        assert response.status_code == status.HTTP_200_OK
        assert invalidate.call_args.kwargs["dry_run"] is True
        assert response.json()["rebuild"]["scheduled"] is False
        task.delay.assert_not_called()

    # --- Response contract ---

    def test_reports_effective_range_when_wider_than_requested(self):
        wide = _invalidation(
            start=datetime(2026, 7, 1, tzinfo=UTC),
            end=datetime(2026, 7, 31, tzinfo=UTC),
        )
        with patch(_INVALIDATE, return_value=wide), patch(_REBUILD_TASK):
            body = self._post().json()

        assert body["effective_range"] == {"date_from": "2026-07-01", "date_to": "2026-07-31"}
        assert any("wider than requested" in note for note in body["notes"])

    def test_effective_range_is_null_when_nothing_matched(self):
        with patch(_INVALIDATE, return_value=_invalidation(jobs_deleted=0)), patch(_REBUILD_TASK):
            body = self._post().json()

        assert body["effective_range"] is None

    def test_zero_resolved_sources_is_called_out(self):
        """Silence here would read as "rebuild scheduled" when in fact nothing could be identified."""
        with patch(_INVALIDATE, return_value=_invalidation(jobs_deleted=0, hashes=0, sources=0)), patch(_REBUILD_TASK):
            body = self._post().json()

        assert body["query_hashes_resolved"] == 0
        assert any("No marketing source could be resolved" in note for note in body["notes"])

    def test_always_warns_about_the_separate_result_cache(self):
        with patch(_INVALIDATE, return_value=_invalidation()), patch(_REBUILD_TASK):
            body = self._post().json()

        assert any("refresh=blocking" in note for note in body["notes"])

    def test_service_failure_returns_500_without_leaking_details(self):
        with patch(_INVALIDATE, side_effect=Exception("clickhouse exploded")), patch(_REBUILD_TASK):
            response = self._post()

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "clickhouse" not in str(response.json()).lower()

    # --- Access control ---

    def test_requires_authentication(self):
        self.client.logout()
        response = self._post()

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_other_teams_jobs_are_untouched(self):
        """End-to-end through the real service: a team can only clear its own bookkeeping."""
        other_team = self.organization.teams.create(name="other")
        other_job = PreaggregationJob.objects.create(
            team=other_team,
            query_hash="shared_looking_hash",
            time_range_start=datetime(2026, 7, 16, tzinfo=UTC),
            time_range_end=datetime(2026, 7, 17, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=datetime(2026, 7, 30, tzinfo=UTC) + timedelta(days=7),
        )

        with patch(f"{_SERVICE}.iter_cost_materializations", return_value=iter([])), patch(_REBUILD_TASK):
            response = self._post()

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert PreaggregationJob.objects.filter(id=other_job.id).exists()
