import os
import re
import json
from datetime import datetime

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework import status

from posthog.clickhouse.client import sync_execute

_FIXTURE_WINDOW = {"date_from": "2025-12-14T00:00:00Z", "date_to": "2025-12-19T00:00:00Z"}
_DENSE_DAY = {"date_from": "2025-12-16T00:00:00Z", "date_to": "2025-12-17T00:00:00Z"}
_INTERVAL_RE = re.compile(r"^\d+[smhd]$")


class TestCountRangesApi(ClickhouseTestMixin, APIBaseTest):
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

    def _ranges(self, query_params, expected_status=status.HTTP_200_OK):
        response = self.client.post(
            f"/api/projects/{self.team.id}/logs/count-ranges",
            data={"query": query_params},
        )
        self.assertEqual(response.status_code, expected_status)
        return response.json() if expected_status == status.HTTP_200_OK else response

    @freeze_time("2025-12-18T12:00:00Z")
    def test_default_target_buckets_picks_12h_interval(self):
        # 5-day window / 10 target buckets => 12-hour interval (deterministic from
        # the picker's "round" interval list).
        response = self._ranges({"dateRange": _FIXTURE_WINDOW})
        self.assertEqual(response["interval"], "12h")
        self.assertGreater(len(response["ranges"]), 0)
        self.assertLessEqual(len(response["ranges"]), 10)
        for bucket in response["ranges"]:
            self.assertGreater(bucket["count"], 0)
            self.assertRegex(response["interval"], _INTERVAL_RE)

    @parameterized.expand(
        [
            (5, "1d"),
            (20, "6h"),
            (50, "2h"),
        ]
    )
    @freeze_time("2025-12-18T12:00:00Z")
    def test_target_buckets_picks_appropriate_interval(self, target, expected_interval):
        response = self._ranges({"dateRange": _FIXTURE_WINDOW, "targetBuckets": target})
        self.assertEqual(response["interval"], expected_interval)

    @freeze_time("2025-12-18T12:00:00Z")
    def test_target_buckets_above_max_is_clamped(self):
        over = self._ranges({"dateRange": _FIXTURE_WINDOW, "targetBuckets": 999})
        capped = self._ranges({"dateRange": _FIXTURE_WINDOW, "targetBuckets": 100})
        self.assertEqual(over["interval"], capped["interval"])
        self.assertEqual(len(over["ranges"]), len(capped["ranges"]))

    @freeze_time("2025-12-18T12:00:00Z")
    def test_empty_window_returns_no_ranges(self):
        response = self._ranges(
            {"dateRange": {"date_from": "2000-01-01T00:00:00Z", "date_to": "2000-01-02T00:00:00Z"}},
        )
        self.assertEqual(response["ranges"], [])

    @parameterized.expand(
        [
            ("severity_info", "severityLevels", ["info"]),
            ("severity_debug", "severityLevels", ["debug"]),
            ("severity_error", "severityLevels", ["error"]),
            ("severity_info_error", "severityLevels", ["info", "error"]),
            ("service_argo_rollouts", "serviceNames", ["argo-rollouts"]),
            ("service_contour", "serviceNames", ["contour"]),
            ("service_argo_rollouts_contour", "serviceNames", ["argo-rollouts", "contour"]),
        ]
    )
    @freeze_time("2025-12-18T12:00:00Z")
    def test_filter_sum_matches_count_endpoint(self, _name, field, value):
        params = {"dateRange": _FIXTURE_WINDOW, field: value}
        ranges_response = self._ranges({**params, "targetBuckets": 50})
        bucket_sum = sum(b["count"] for b in ranges_response["ranges"])

        count_response = self.client.post(
            f"/api/projects/{self.team.id}/logs/count",
            data={"query": params},
        )
        self.assertEqual(count_response.status_code, status.HTTP_200_OK)
        self.assertEqual(bucket_sum, count_response.json()["count"])

    @freeze_time("2025-12-18T12:00:00Z")
    def test_buckets_ordered_ascending_and_aligned(self):
        response = self._ranges({"dateRange": _DENSE_DAY, "targetBuckets": 24})
        ranges = response["ranges"]
        self.assertGreater(len(ranges), 1)
        for prev, curr in zip(ranges, ranges[1:]):
            self.assertLess(prev["date_from"], curr["date_from"])
        for bucket in ranges:
            df = datetime.fromisoformat(bucket["date_from"])
            dt_ = datetime.fromisoformat(bucket["date_to"])
            self.assertGreater(dt_, df)

    @freeze_time("2025-12-18T12:00:00Z")
    def test_recursion_happy_path(self):
        wide = self._ranges({"dateRange": _FIXTURE_WINDOW, "targetBuckets": 10})
        densest = max(wide["ranges"], key=lambda b: b["count"])

        narrow = self._ranges(
            {
                "dateRange": {"date_from": densest["date_from"], "date_to": densest["date_to"]},
                "targetBuckets": 10,
            },
        )
        self.assertGreater(len(narrow["ranges"]), 0)
        narrow_sum = sum(b["count"] for b in narrow["ranges"])
        self.assertLessEqual(narrow_sum, densest["count"])
        self.assertGreater(narrow_sum, 0)

    @freeze_time("2025-12-18T12:00:00Z")
    def test_no_filtergroup_does_not_crash(self):
        response = self._ranges({"dateRange": _DENSE_DAY})
        self.assertGreater(len(response["ranges"]), 0)

    @freeze_time("2025-12-18T12:00:00Z")
    def test_defaults_date_range_to_last_hour(self):
        response = self._ranges({})
        self.assertEqual(response["ranges"], [])
