from datetime import UTC, datetime

from posthog.test.base import ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.feature_flags.backend.request_usage import (
    REQUEST_USAGE_QUERY_SETTINGS,
    aggregate_feature_flag_request_usage,
    parse_sdk_breakdown,
    query_feature_flag_request_usage,
)


class TestFeatureFlagRequestUsageQuery(ClickhouseTestMixin, TestCase):
    @parameterized.expand(
        [
            ("missing breakdown", "", [("other", 10)]),
            ("partial breakdown", '{"posthog-node": 4}', [("other", 6), ("posthog-node", 4)]),
        ]
    )
    def test_attributes_unclassified_billed_requests_to_other(
        self, _name: str, sdk_breakdown: str, expected: list[tuple[str, int]]
    ) -> None:
        results = aggregate_feature_flag_request_usage(
            [(datetime(2026, 8, 20, tzinfo=UTC), "remote_evaluation", 10, sdk_breakdown)]
        )
        assert [(result.sdk, result.request_count) for result in results] == expected

    @parameterized.expand(
        [
            ("malformed JSON", "{not-json", {}),
            ("non-object JSON", "[]", {}),
            ("invalid values", '{"posthog-node": -1, "posthog-python": "2"}', {}),
            ("fully attributed", '{"posthog-node": 4, "posthog-python": 6}', {"posthog-node": 4, "posthog-python": 6}),
        ]
    )
    def test_parses_sdk_breakdown(self, _name: str, raw_breakdown: str, expected: dict[str, int]) -> None:
        assert parse_sdk_breakdown(raw_breakdown) == expected

    @patch("products.feature_flags.backend.request_usage.sync_execute")
    def test_clickhouse_query_is_scoped_and_weights_local_requests(self, mock_sync_execute) -> None:
        mock_sync_execute.return_value = [
            (datetime(2026, 8, 20, tzinfo=UTC), "local_evaluation", 4, '{"posthog-node": 4}')
        ]
        results = query_feature_flag_request_usage(
            team_id=123,
            date_from=datetime(2026, 8, 20, tzinfo=UTC),
            date_to=datetime(2026, 8, 21, tzinfo=UTC),
            time_interval="day",
        )
        query, params = mock_sync_execute.call_args.args[:2]
        assert "distinct_id = toString(%(team_id)s)" in query
        assert params["team_id"] == 123
        assert mock_sync_execute.call_args.kwargs["team_id"] == 123
        assert mock_sync_execute.call_args.kwargs["settings"] == REQUEST_USAGE_QUERY_SETTINGS
        assert mock_sync_execute.call_args.kwargs["ch_user"] == ClickHouseUser.APP
        assert results[0].request_count == 4
        assert results[0].billing_units == 40

    def test_clickhouse_query_executes_against_usage_events(self) -> None:
        organization = Organization.objects.create(name="Internal analytics")
        analytics_team = Team.objects.create(id=2, organization=organization, name="Internal analytics")
        _create_event(
            team=analytics_team,
            distinct_id="123",
            event="decide usage",
            timestamp=datetime(2026, 8, 20, 12, tzinfo=UTC),
            properties={
                "count": 7,
                "sdk_breakdown": '{"posthog-node": 7}',
                "token": "request-usage-test-token",
            },
        )
        _create_event(
            team=analytics_team,
            distinct_id="123",
            event="local evaluation usage",
            timestamp=datetime(2026, 8, 20, 12, 35, tzinfo=UTC),
            properties={
                "count": 3,
                "sdk_breakdown": '{"posthog-python": 3}',
                "token": "request-usage-test-token",
            },
        )
        _create_event(
            team=analytics_team,
            distinct_id="123",
            event="decide usage",
            timestamp=datetime(2026, 8, 20, 12, 45, tzinfo=UTC),
            properties={
                "count": 100,
                "sdk_breakdown": '{"wrong-token-sdk": 100}',
                "token": "wrong-token",
            },
        )
        flush_persons_and_events()
        with self.settings(DECIDE_BILLING_ANALYTICS_TOKEN="request-usage-test-token"):
            hourly_results = query_feature_flag_request_usage(
                team_id=123,
                date_from=datetime(2026, 8, 20, tzinfo=UTC),
                date_to=datetime(2026, 8, 21, tzinfo=UTC),
                time_interval="hour",
            )
            daily_results = query_feature_flag_request_usage(
                team_id=123,
                date_from=datetime(2026, 8, 20, tzinfo=UTC),
                date_to=datetime(2026, 8, 21, tzinfo=UTC),
                time_interval="day",
            )

        assert [(item.request_type.value, item.sdk, item.request_count) for item in hourly_results] == [
            ("local_evaluation", "posthog-python", 3),
            ("remote_evaluation", "posthog-node", 7),
        ]
        assert {item.bucket for item in hourly_results} == {datetime(2026, 8, 20, 12, tzinfo=UTC)}
        assert {item.bucket for item in daily_results} == {datetime(2026, 8, 20, tzinfo=UTC)}
