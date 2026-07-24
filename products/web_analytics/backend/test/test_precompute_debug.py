from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.api.precompute_debug import _fetch_samples_from_query_log

_MODULE = "products.web_analytics.backend.api.precompute_debug"


def _make_job(team, *, query_hash, days_ago_start, status=PreaggregationJob.Status.READY, ttl_hours=6):
    now = timezone.now()
    start = now - timedelta(days=days_ago_start)
    return PreaggregationJob.objects.create(
        team=team,
        time_range_start=start,
        time_range_end=start + timedelta(days=1),
        query_hash=query_hash,
        status=status,
        computed_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=ttl_hours),
    )


@patch(f"{_MODULE}.is_cloud", return_value=True)
class TestPrecomputeDebugAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.pk}/web_analytics_precompute_debug/state/"

    @parameterized.expand(
        [
            # Cloud + non-staff must be refused: this endpoint exposes internal
            # precompute state and originating queries.
            ("non_staff_forbidden", False, 403),
            ("staff_allowed", True, 200),
        ]
    )
    @patch(f"{_MODULE}._fetch_samples_from_query_log", return_value={})
    def test_staff_gate(self, _name, is_staff, expected_status, _samples, _is_cloud):
        self.user.is_staff = is_staff
        self.user.save()
        response = self.client.get(self._url())
        assert response.status_code == expected_status

    @patch(f"{_MODULE}._fetch_samples_from_query_log", return_value={})
    def test_groups_buckets_by_hash_with_ttl(self, _samples, _is_cloud):
        self.user.is_staff = True
        self.user.save()
        _make_job(self.team, query_hash="a" * 64, days_ago_start=1)
        _make_job(self.team, query_hash="a" * 64, days_ago_start=2, status=PreaggregationJob.Status.PENDING)
        # Expired bucket: negative TTL remaining must be reported, not hidden.
        _make_job(self.team, query_hash="b" * 64, days_ago_start=1, ttl_hours=-2)

        response = self.client.get(self._url())
        assert response.status_code == 200
        data = response.json()
        assert data["total_hashes"] == 2
        groups = {g["query_hash"]: g for g in data["groups"]}
        assert groups["a" * 64]["job_count"] == 2
        assert groups["a" * 64]["status_counts"] == {"ready": 1, "pending": 1}
        assert groups["b" * 64]["buckets"][0]["ttl_seconds_remaining"] < 0

    @patch(f"{_MODULE}._fetch_samples_from_query_log", return_value={})
    def test_scoped_to_team(self, _samples, _is_cloud):
        # Another team's jobs must never appear — this is per-team debug state.
        self.user.is_staff = True
        self.user.save()
        other_team = self.organization.teams.create(name="other")
        _make_job(other_team, query_hash="c" * 64, days_ago_start=1)

        response = self.client.get(self._url())
        assert response.status_code == 200
        assert response.json()["total_hashes"] == 0

    def test_sample_index_mapping(self, _is_cloud):
        # multiSearchFirstIndex is 1-based: row idx=2 must map to the SECOND hash,
        # and out-of-range indexes must be dropped, not crash or mislabel.
        now = timezone.now()
        with patch(
            f"{_MODULE}.sync_execute",
            return_value=[
                (2, "web_stats_lazy_insert", "webAnalyticsEagerBaselineWarming", '{"kind":"WebStatsTableQuery"}', now),
                (99, "bogus", "", "{}", now),
            ],
        ):
            samples = _fetch_samples_from_query_log(self.team.pk, {"hash_one": "id1", "hash_two": "id2"})
        assert set(samples.keys()) == {"hash_two"}
        assert samples["hash_two"]["query_type"] == "web_stats_lazy_insert"
