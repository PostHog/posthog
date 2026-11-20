import datetime as dt
from collections.abc import Callable

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from posthog.models import User

from products.access_control.backend.facade.testing import PropertyAccess, set_member_property_access
from products.logs.backend.alert_check_query import AlertCheckQuery
from products.logs.backend.anomaly_scan import TimeRange, fetch_bucket_counts
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.natural_language_query import gather_filter_context
from products.logs.backend.pattern_diff import _first_seen_ever
from products.logs.backend.series_bands import fetch_series_slot_rows
from products.logs.backend.test.volume_rollup_fixtures import insert_logs_and_rollups, log_row

_NOW = dt.datetime(2026, 3, 4, 13, 0, tzinfo=dt.UTC)
_START = dt.datetime(2026, 3, 4, 12, 0, tzinfo=dt.UTC)
_PIPELINE = "posthog-internal-hog-functions"
_APP = "pipeline-access-app"
_PATTERN = "step <*> failed"


class TestPipelineLogAccess(ClickhouseTestMixin, APIBaseTest):
    """Every Logs reader that a member can reach hides pipeline logs from restricted members only."""

    def setUp(self) -> None:
        super().setUp()
        insert_logs_and_rollups(
            [
                log_row(self.team.id, _START + dt.timedelta(minutes=minute), service=service, pattern=_PATTERN)
                for service in (_PIPELINE, _APP)
                for minute in range(3)
            ]
        )

    def _alert_count(self, service: str, user: User | None) -> int:
        alert = LogsAlertConfiguration(team=self.team, filters={"serviceNames": [service]}, window_minutes=60)
        return AlertCheckQuery(team=self.team, alert=alert, date_from=_START, date_to=_NOW, user=user).execute().count

    def _anomaly_count(self, service: str, user: User | None) -> int:
        counts = fetch_bucket_counts(self.team, service, [TimeRange(start=_START, end=_NOW)], user=user)
        return sum(sum(by_bucket.values()) for by_bucket in counts.values())

    def _series_count(self, service: str, user: User | None) -> int:
        return len(fetch_series_slot_rows(self.team, service, _START, _NOW, 60, user=user))

    def _first_seen_count(self, service: str, user: User | None) -> int:
        query = LogsQuery(
            dateRange=DateRange(date_from=_START.isoformat(), date_to=_NOW.isoformat()),
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
            severityLevels=[],
            serviceNames=[service],
        )
        entries = [{"pattern": {"match_patterns": [_PATTERN]}}]
        return len(_first_seen_ever(self.team, query, entries, 1, _NOW, user=user) or {})

    def _search_suggestion_count(self, service: str, user: User | None) -> int:
        date_range = DateRange(date_from=_START.isoformat(), date_to=_NOW.isoformat())
        return int(service in gather_filter_context(self.team, date_range, user).services)

    def _readers(self) -> dict[str, Callable[[str, User | None], int]]:
        return {
            "alert_check": self._alert_count,
            "anomaly_scan": self._anomaly_count,
            "series_bands": self._series_count,
            "pattern_first_seen": self._first_seen_count,
            "search_suggestions": self._search_suggestion_count,
        }

    @parameterized.expand(
        [
            (reader, access)
            for reader in ("alert_check", "anomaly_scan", "series_bands", "pattern_first_seen", "search_suggestions")
            for access in ("restricted", "granted", "admin")
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_reader_follows_the_callers_property_access(self, reader: str, access: PropertyAccess) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)
        read = self._readers()[reader]

        assert read(_APP, self.user) > 0
        assert (read(_PIPELINE, self.user) > 0) == (access != "restricted")
        assert read(_PIPELINE, None) == 0

    @parameterized.expand([("restricted", 0), ("granted", 3), ("admin", 3)])
    @time_machine.travel(_NOW, tick=False)
    def test_alert_simulation_follows_property_access(self, access: PropertyAccess, expected: int) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/simulate/",
                {
                    "filters": {"serviceNames": [_PIPELINE]},
                    "threshold_count": 100,
                    "threshold_operator": "above",
                    "window_minutes": 60,
                    "date_from": "-2h",
                },
                format="json",
            )

        assert response.status_code == 200, response.json()
        assert max(bucket["count"] for bucket in response.json()["buckets"]) == expected

    @parameterized.expand(
        [
            ("restricted_pipeline", "restricted", [_PIPELINE], 403),
            ("restricted_all_services", "restricted", [], 403),
            ("restricted_app", "restricted", [_APP], 201),
            ("granted_pipeline", "granted", [_PIPELINE], 201),
            ("admin_pipeline", "admin", [_PIPELINE], 201),
        ]
    )
    def test_alert_on_pipeline_logs_follows_property_access(
        self, _name: str, access: PropertyAccess, services: list[str], expected: int
    ) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/",
                {
                    "name": "Pipeline alert",
                    "filters": {"serviceNames": services, "severityLevels": ["error"]},
                    "threshold_count": 0,
                    "threshold_operator": "above",
                    "window_minutes": 5,
                },
                format="json",
            )

            listed = self.client.get(f"/api/projects/{self.team.pk}/logs/alerts/").json()["results"]

        assert response.status_code == expected, response.json()
        assert [alert["name"] for alert in listed] == (["Pipeline alert"] if expected == 201 else [])

    @parameterized.expand(
        [
            ("rename", True, {"name": "Renamed"}, 200),
            (
                "rename_from_edit_form",
                True,
                {"name": "Renamed", "filters": {"serviceNames": [_PIPELINE]}},
                200,
            ),
            ("snooze", True, {"snooze_until": "2099-01-01T00:00:00Z"}, 200),
            ("change_filters", True, {"filters": {"serviceNames": [_PIPELINE], "severityLevels": ["warn"]}}, 403),
            ("turn_on", False, {"enabled": True}, 403),
            ("change_routing_labels", True, {"labels": {"team": "payments"}}, 403),
            ("send_no_routing_labels", True, {"labels": {}}, 200),
        ]
    )
    def test_restricted_member_updating_a_pipeline_log_alert(
        self, _name: str, enabled: bool, change: dict, expected: int
    ) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True):
            alert = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/",
                {
                    "name": "Pipeline alert",
                    "enabled": enabled,
                    "filters": {"serviceNames": [_PIPELINE]},
                    "threshold_count": 0,
                    "threshold_operator": "above",
                    "window_minutes": 5,
                },
                format="json",
            ).json()
            set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/logs/alerts/{alert['id']}/", change, format="json"
            )

        assert response.status_code == expected, response.json()

    @parameterized.expand([("restricted", 403), ("granted", 201), ("admin", 201)])
    def test_destination_on_pipeline_log_alert_follows_property_access(
        self, access: PropertyAccess, expected: int
    ) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True):
            alert = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/",
                {
                    "name": "Pipeline alert",
                    "filters": {"serviceNames": [_PIPELINE]},
                    "threshold_count": 0,
                    "threshold_operator": "above",
                    "window_minutes": 5,
                },
                format="json",
            ).json()
            set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

            response = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/{alert['id']}/destinations/",
                {"type": "webhook", "webhook_url": "https://hooks.example.com/alert"},
                format="json",
            )

        assert (response.status_code == 403) == (expected == 403), response.json()
