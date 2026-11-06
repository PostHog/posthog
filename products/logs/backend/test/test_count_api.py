import os
import json

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework import status

from posthog.api.query import CONCURRENCY_LIMIT_USER_MESSAGE
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.limit import get_logs_api_team_rate_limiter

_FIXTURE_WINDOW = {"date_from": "2025-12-14T00:00:00Z", "date_to": "2025-12-19T00:00:00Z"}


class TestCountApi(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with open(os.path.join(os.path.dirname(__file__), "test_logs.jsonnd")) as f:
            sql = ""
            for line in f:
                log_item = json.loads(line)
                log_item["team_id"] = cls.team.id
                sql += json.dumps(log_item) + "\n"
            sync_execute(f"""
                INSERT INTO logs
                FORMAT JSONEachRow
                {sql}
            """)

    def _count(self, query_params, expected_status=status.HTTP_200_OK):
        response = self.client.post(f"/api/projects/{self.team.id}/logs/count", data={"query": query_params})
        self.assertEqual(response.status_code, expected_status)
        return response.json() if expected_status == status.HTTP_200_OK else response

    @parameterized.expand(
        [
            ("full_window", _FIXTURE_WINDOW, 1011),
            ("empty_window", {"date_from": "2000-01-01T00:00:00Z", "date_to": "2000-01-02T00:00:00Z"}, 0),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_date_range(self, _name, date_range, expected):
        response = self._count({"dateRange": date_range})
        self.assertEqual(response["count"], expected)

    @parameterized.expand(
        [
            (["info"], 848),
            (["debug"], 66),
            (["error"], 97),
            (["info", "error"], 945),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_severity_filter(self, severities, expected):
        response = self._count({"dateRange": _FIXTURE_WINDOW, "severityLevels": severities})
        self.assertEqual(response["count"], expected)

    @parameterized.expand(
        [
            (["argo-rollouts"], 100),
            (["contour"], 100),
            (["argo-rollouts", "contour"], 200),
            (["nonexistent-service-xyz"], 0),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_service_filter(self, services, expected):
        response = self._count({"dateRange": _FIXTURE_WINDOW, "serviceNames": services})
        self.assertEqual(response["count"], expected)

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_search_term_matches_body_text(self):
        response = self._count({"dateRange": _FIXTURE_WINDOW, "searchTerm": "connection refused"})
        self.assertEqual(response["count"], 1)

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_defaults_date_range_to_last_hour(self):
        # No dateRange in request; default should be -1h relative to frozen "now".
        # Fixture's latest timestamp is 2025-12-18T02:00Z — outside the last hour.
        response = self._count({})
        self.assertEqual(response["count"], 0)

    def test_count_rejects_non_object_query(self):
        # A non-object `query` (e.g. a bare string) used to crash with an unhandled
        # AttributeError on the first `.get()` call instead of a clean 400.
        response = self.client.post(f"/api/projects/{self.team.id}/logs/count", data={"query": "not-an-object"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            # Multi-day window — exercises full WHERE clause
            ("full_window_no_filters", _FIXTURE_WINDOW, {}),
            ("full_window_severity_info", _FIXTURE_WINDOW, {"severityLevels": ["info"]}),
            ("full_window_service_argo", _FIXTURE_WINDOW, {"serviceNames": ["argo-rollouts"]}),
            # Sub-day window — the case that would fail if count regressed to toStartOfDay precision
            (
                "sub_day_hour",
                {"date_from": "2025-12-16T09:00:00Z", "date_to": "2025-12-16T10:00:00Z"},
                {},
            ),
        ]
    )
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_count_matches_sparkline_sum(self, _name, date_range, filters):
        # Cross-verify: sum of sparkline bucket counts should equal the scalar count
        # for the same query. Catches drift between the two endpoints' WHERE handling.
        # An explicit empty filterGroup is passed because sparkline currently requires it.
        params = {
            "dateRange": date_range,
            "filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]},
            **filters,
        }

        count_result = self._count(params)
        sparkline_response = self.client.post(
            f"/api/projects/{self.team.id}/logs/sparkline",
            data={"query": params},
        )
        self.assertEqual(sparkline_response.status_code, status.HTTP_200_OK)

        sparkline_sum = sum(bucket["count"] for bucket in sparkline_response.json())
        self.assertEqual(count_result["count"], sparkline_sum)

    def _post_count_with_personal_api_key(self):
        token = self.create_personal_api_key_with_scopes(["logs:read"])
        self.client.logout()
        return self.client.post(
            f"/api/projects/{self.team.id}/logs/count",
            data={"query": {"dateRange": _FIXTURE_WINDOW}},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_full_team_concurrency_limit_refuses_personal_api_key_requests_but_not_sessions(self):
        limiter = get_logs_api_team_rate_limiter()
        held_slots = [limiter.use(team_id=self.team.id) for _ in range(limiter.max_concurrency)]
        try:
            with patch.object(limiter, "retry_timeout", 0):
                session_response = self.client.post(
                    f"/api/projects/{self.team.id}/logs/count",
                    data={"query": {"dateRange": _FIXTURE_WINDOW}},
                    content_type="application/json",
                )
                api_key_response = self._post_count_with_personal_api_key()
        finally:
            for slot in held_slots:
                if slot is not None:
                    limiter.release(slot)

        self.assertEqual(session_response.status_code, status.HTTP_200_OK)
        self.assertEqual(api_key_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertTrue(api_key_response.json()["detail"].startswith(CONCURRENCY_LIMIT_USER_MESSAGE))
        self.assertEqual(api_key_response["Retry-After"], "1")

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_personal_api_key_requests_release_their_concurrency_slot(self):
        limiter = get_logs_api_team_rate_limiter()

        statuses = [self._post_count_with_personal_api_key().status_code for _ in range(limiter.max_concurrency + 1)]

        self.assertEqual(statuses, [status.HTTP_200_OK] * (limiter.max_concurrency + 1))

    @override_settings(DEBUG=True)
    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_personal_api_key_requests_release_their_concurrency_slot_when_the_handler_raises(self):
        limiter = get_logs_api_team_rate_limiter()
        self.client.raise_request_exception = False

        with patch(
            "products.logs.backend.presentation.views.api.CountQueryRunner.run", side_effect=RuntimeError("boom")
        ):
            response = self._post_count_with_personal_api_key()

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

        self.assertEqual(limiter.redis_client.zcard(f"logs_api:query:per-team:{self.team.id}"), 0)

    @time_machine.travel("2025-12-18T12:00:00Z", tick=False)
    def test_personal_api_key_requests_pass_when_the_limiter_redis_is_down(self):
        broken_redis = MagicMock()
        broken_redis.eval.side_effect = RedisConnectionError()

        with patch.object(get_logs_api_team_rate_limiter(), "redis_client", broken_redis):
            response = self._post_count_with_personal_api_key()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
