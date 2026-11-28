import datetime as dt
from collections.abc import Callable

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.db import transaction
from django.utils import timezone

from parameterized import parameterized

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from posthog.models import Team, User

from products.access_control.backend.facade.testing import PropertyAccess, set_member_property_access
from products.alerts_platform.backend.facade import testing as platform_testing
from products.logs.backend.alert_check_query import AlertCheckQuery, BatchedAlertCheckQuery
from products.logs.backend.anomaly_scan import TimeRange, fetch_bucket_counts
from products.logs.backend.has_logs_query_runner import HasLogsQueryRunner
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.natural_language_query import gather_filter_context
from products.logs.backend.pattern_diff import _first_seen_ever
from products.logs.backend.platform_ownership import hand_over
from products.logs.backend.series_bands import fetch_series_slot_rows
from products.logs.backend.test.volume_rollup_fixtures import insert_logs_and_rollups, log_row

_NOW = dt.datetime(2026, 3, 4, 13, 0, tzinfo=dt.UTC)
_START = dt.datetime(2026, 3, 4, 12, 0, tzinfo=dt.UTC)
_PIPELINE = "posthog-internal-hog-functions"
_APP = "pipeline-access-app"
_PATTERN = "step <*> failed"


class TestPipelineLogAccess(ClickhouseTestMixin, APIBaseTest):
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
            for access in ("restricted", "granted")
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_reader_follows_the_callers_property_access(self, reader: str, access: PropertyAccess) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)
        read = self._readers()[reader]

        assert read(_APP, self.user) > 0
        assert (read(_PIPELINE, self.user) > 0) == (access != "restricted")
        assert (read(_PIPELINE, None) > 0) == (reader == "alert_check")

    def test_has_logs_counts_pipeline_logs_under_a_team_rule(self) -> None:
        pipeline_only = Team.objects.create(organization=self.organization, name="Pipeline only")
        insert_logs_and_rollups([log_row(pipeline_only.id, _START, service=_PIPELINE, pattern=_PATTERN)])
        set_member_property_access(team=pipeline_only, membership=self.organization_membership, access="restricted")

        assert HasLogsQueryRunner(pipeline_only).run() is True

    @time_machine.travel(_NOW, tick=False)
    def test_scheduled_alert_check_counts_pipeline_logs_under_a_team_rule(self) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")
        alert = LogsAlertConfiguration.objects.create(
            team=self.team, name="pipeline errors", filters={"serviceNames": [_PIPELINE]}, window_minutes=60
        )

        result = BatchedAlertCheckQuery(team=self.team, alerts=[alert], date_from=_START, date_to=_NOW).execute_periods(
            60, 1
        )

        assert sum(bucket.count for bucket in result.per_alert[str(alert.id)]) == 3

    @parameterized.expand([("restricted", 0), ("granted", 3)])
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
            ("restricted_pipeline_draft", "restricted", [_PIPELINE], 403, False),
            ("granted_pipeline", "granted", [_PIPELINE], 201),
        ]
    )
    def test_alert_on_pipeline_logs_follows_property_access(
        self, _name: str, access: PropertyAccess, services: list[str], expected: int, enabled: bool = True
    ) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

        with patch("posthoganalytics.feature_enabled", return_value=True):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/",
                {
                    "name": "Pipeline alert",
                    "enabled": enabled,
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
            ("snooze", True, {"snooze_until": "2099-01-01T00:00:00Z"}, 200),
            ("change_filters", True, {"filters": {"serviceNames": [_PIPELINE], "severityLevels": ["warn"]}}, 403),
            ("turn_on", False, {"enabled": True}, 403),
            ("rename_draft", False, {"name": "Renamed"}, 200),
            ("change_draft_filters", False, {"filters": {"severityLevels": ["warn"]}}, 403),
            ("change_routing_labels", True, {"labels": {"team": "payments"}}, 403),
            ("change_grouping", True, {"grouping": {"mode": "by_result_labels", "keys": ["service_name"]}}, 403),
            ("change_threshold", True, {"threshold_count": 5}, 403),
            ("change_window", True, {"window_minutes": 60}, 403),
            ("change_evaluation", True, {"evaluation_periods": 3, "datapoints_to_alarm": 2}, 200),
            ("move_off_pipeline_logs", True, {"filters": {"serviceNames": [_APP]}}, 403),
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

    def test_restricted_member_renames_a_grouped_pipeline_log_alert_without_the_defaulted_grouping_fields(
        self,
    ) -> None:
        grouping = {"mode": "by_result_labels", "keys": ["service_name"]}
        with patch("posthoganalytics.feature_enabled", return_value=True):
            alert = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/",
                {
                    "name": "Pipeline alert",
                    "filters": {"serviceNames": [_PIPELINE]},
                    "threshold_count": 0,
                    "threshold_operator": "above",
                    "window_minutes": 5,
                    "grouping": grouping,
                },
                format="json",
            ).json()
            set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/logs/alerts/{alert['id']}/",
                {"name": "Renamed", "grouping": grouping},
                format="json",
            )

        assert response.status_code == 200, response.json()

    def test_restricted_member_renames_a_pipeline_log_alert_by_sending_it_back_whole(self) -> None:
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
            set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")
            stored = self.client.get(f"/api/projects/{self.team.pk}/logs/alerts/{alert['id']}/").json()
            writable = (
                "filters",
                "threshold_count",
                "threshold_operator",
                "window_minutes",
                "grouping",
                "labels",
                "annotations",
            )

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/logs/alerts/{alert['id']}/",
                {**{key: stored[key] for key in writable}, "name": "Renamed"},
                format="json",
            )

        assert response.status_code == 200, response.json()

    @parameterized.expand(
        [
            ("restricted_pipeline", "restricted", [_PIPELINE], 403),
            ("restricted_all_services", "restricted", [], 403),
            ("restricted_app", "restricted", [_APP], 201),
            ("restricted_pipeline_draft", "restricted", [_PIPELINE], 403, False),
            ("granted_pipeline", "granted", [_PIPELINE], 201),
        ]
    )
    def test_platform_logs_alert_follows_property_access(
        self, _name: str, access: PropertyAccess, services: list[str], expected: int, enabled: bool = True
    ) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/platform_alerts/",
                {
                    "source_kind": "logs",
                    "enabled": enabled,
                    "source_config": {
                        "filters": {"serviceNames": services},
                        "condition": {"threshold_count": 0, "threshold_operator": "above", "window_minutes": 5},
                    },
                },
                format="json",
            )

        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("rename", {"name": "Renamed"}, 200),
            ("route", {"labels": {"team": "payments"}}, 403),
            ("group", {"grouping": {"mode": "by_result_labels", "keys": ["service_name"]}}, 403),
            (
                "move_off_pipeline_logs",
                {
                    "source_config": {
                        "filters": {"serviceNames": [_APP]},
                        "condition": {"threshold_count": 0, "threshold_operator": "above", "window_minutes": 5},
                    }
                },
                403,
            ),
        ]
    )
    def test_restricted_member_edits_a_pipeline_platform_alert_with_its_config_unchanged(
        self, _name: str, change: dict, expected: int
    ) -> None:
        config = {
            "filters": {"serviceNames": [_PIPELINE]},
            "condition": {"threshold_count": 0, "threshold_operator": "above", "window_minutes": 5},
        }
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True):
            alert = self.client.post(
                f"/api/projects/{self.team.pk}/platform_alerts/",
                {"source_kind": "logs", "source_config": config},
                format="json",
            ).json()
            set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")
            stored = self.client.get(f"/api/projects/{self.team.pk}/platform_alerts/{alert['id']}/").json()

            response = self.client.patch(
                f"/api/projects/{self.team.pk}/platform_alerts/{alert['id']}/",
                {"source_config": stored["source_config"], **change},
                format="json",
            )

        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("logs_restricted", "logs", "restricted", 403),
            ("logs_granted", "logs", "granted", 400),
            ("platform_restricted", "platform", "restricted", 403),
            ("platform_granted", "platform", "granted", 400),
        ]
    )
    def test_reset_of_a_pipeline_log_alert_follows_property_access(
        self, _name: str, api: str, access: PropertyAccess, expected: int
    ) -> None:
        condition = {"threshold_count": 0, "threshold_operator": "above", "window_minutes": 5}
        filters = {"serviceNames": [_PIPELINE]}
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True),
        ):
            if api == "logs":
                base = f"/api/projects/{self.team.pk}/logs/alerts/"
                created = self.client.post(
                    base, {"name": "Pipeline alert", "filters": filters, **condition}, format="json"
                )
            else:
                base = f"/api/projects/{self.team.pk}/platform_alerts/"
                created = self.client.post(
                    base,
                    {"source_kind": "logs", "source_config": {"filters": filters, "condition": condition}},
                    format="json",
                )
            set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

            response = self.client.post(f"{base}{created.json()['id']}/reset/")

        # The alert is not broken, so a member allowed past the check gets the "only broken alerts" error.
        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [
            ("not_an_object", []),
            ("services_not_a_list", {"filters": {"serviceNames": 1}}),
            ("services_not_names", {"filters": {"serviceNames": [{}]}}),
        ]
    )
    def test_platform_logs_alert_with_a_malformed_config_is_a_validation_error(
        self, _name: str, source_config: object
    ) -> None:
        set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")

        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True):
            response = self.client.post(
                f"/api/projects/{self.team.pk}/platform_alerts/",
                {"source_kind": "logs", "source_config": source_config},
                format="json",
            )

        assert response.status_code == 400, response.json()

    @parameterized.expand([("restricted", True), ("granted", False)])
    def test_destination_on_pipeline_log_alert_follows_property_access(
        self, access: PropertyAccess, refused: bool
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

        assert (response.status_code == 403) == refused, response.json()

    @parameterized.expand([("to_pipeline_logs", _APP, _PIPELINE, True), ("to_app_logs", _PIPELINE, _APP, False)])
    def test_destination_on_a_handed_over_alert_follows_its_current_filters(
        self, _name: str, service_on_logs_row: str, current_service: str, refused: bool
    ) -> None:
        with patch("posthoganalytics.feature_enabled", return_value=True):
            alert = LogsAlertConfiguration.objects.create(
                team=self.team,
                created_by=self.user,
                name="Handed over alert",
                filters={"serviceNames": [service_on_logs_row]},
                threshold_count=0,
                threshold_operator="above",
                window_minutes=5,
            )
            with transaction.atomic():
                assert hand_over(LogsAlertConfiguration.objects.select_for_update().get(pk=alert.pk), timezone.now())
            edited = self.client.patch(
                f"/api/projects/{self.team.pk}/logs/alerts/{alert.pk}/",
                {"filters": {"serviceNames": [current_service]}},
                format="json",
            )
            assert edited.status_code == 200, edited.json()
            set_member_property_access(team=self.team, membership=self.organization_membership, access="restricted")

            response = self.client.post(
                f"/api/projects/{self.team.pk}/logs/alerts/{alert.pk}/destinations/",
                {"type": "webhook", "webhook_url": "https://hooks.example.com/alert"},
                format="json",
            )

        assert (response.status_code == 403) == refused, response.json()

    @parameterized.expand(
        [
            ("logs_restricted_pipeline", "logs", "restricted", _PIPELINE, None, None),
            ("logs_restricted_app", "logs", "restricted", _APP, None, 6),
            ("logs_granted_pipeline", "logs", "granted", _PIPELINE, None, 6),
            ("logs_restricted_moved_off_pipeline", "logs", "restricted", _PIPELINE, "move_to_app", None),
            (
                "logs_restricted_moved_off_pipeline_and_disabled",
                "logs",
                "restricted",
                _PIPELINE,
                "move_and_disable",
                None,
            ),
            ("logs_restricted_app_disabled", "logs", "restricted", _APP, "disable", 6),
            ("platform_restricted_pipeline", "platform", "restricted", _PIPELINE, None, None),
            ("platform_restricted_app", "platform", "restricted", _APP, None, 6),
            ("platform_granted_pipeline", "platform", "granted", _PIPELINE, None, 6),
            ("platform_restricted_moved_off_pipeline", "platform", "restricted", _PIPELINE, "move_to_app", None),
            (
                "platform_restricted_moved_off_pipeline_and_disabled",
                "platform",
                "restricted",
                _PIPELINE,
                "move_and_disable",
                None,
            ),
            ("platform_restricted_app_disabled", "platform", "restricted", _APP, "disable", 6),
        ]
    )
    def test_alert_history_counts_follow_property_access(
        self, _name: str, api: str, access: PropertyAccess, service: str, edit: str | None, expected: int | None
    ) -> None:
        filters = {"serviceNames": [service]}
        condition = {"threshold_count": 0, "threshold_operator": "above", "window_minutes": 5}
        with (
            patch("posthoganalytics.feature_enabled", return_value=True),
            patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True),
        ):
            if api == "logs":
                logs_alert = LogsAlertConfiguration.objects.create(
                    team=self.team, created_by=self.user, name="Alert", filters=filters, **condition
                )
                LogsAlertEvent.objects.create(
                    alert=logs_alert,
                    threshold_breached=True,
                    state_before="not_firing",
                    state_after="firing",
                    result_count=6,
                )
                url = f"/api/projects/{self.team.pk}/logs/alerts/{logs_alert.pk}/events/"
            else:
                alert = self.client.post(
                    f"/api/projects/{self.team.pk}/platform_alerts/",
                    {"source_kind": "logs", "source_config": {"filters": filters, "condition": condition}},
                    format="json",
                ).json()
                platform_testing.record_check(
                    alert["id"],
                    team_id=self.team.id,
                    at=timezone.now() - dt.timedelta(minutes=5),
                    previous_state="not_firing",
                    state="firing",
                    value=6,
                )
                url = f"/api/projects/{self.team.pk}/platform_alerts/{alert['id']}/events/"
            if edit is not None:
                app_filters = {"serviceNames": [_APP]}
                move = (
                    {"filters": app_filters}
                    if api == "logs"
                    else {"source_config": {"filters": app_filters, "condition": condition}}
                )
                body = {
                    "move_to_app": move,
                    "move_and_disable": {**move, "enabled": False},
                    "disable": {"enabled": False},
                }[edit]
                with self.captureOnCommitCallbacks(execute=True):
                    edited = self.client.patch(url.removesuffix("events/"), body, format="json")
                assert edited.status_code == 200, edited.json()
            set_member_property_access(team=self.team, membership=self.organization_membership, access=access)

            response = self.client.get(url)

        assert response.status_code == 200, response.json()
        events = response.json()
        events = events["results"] if api == "logs" else events
        count_field = "result_count" if api == "logs" else "value"
        assert [
            (event["state"] if api == "platform" else event["state_after"], event[count_field])
            for event in events
            if event["kind"] == "check"
        ] == [("firing", expected)]
