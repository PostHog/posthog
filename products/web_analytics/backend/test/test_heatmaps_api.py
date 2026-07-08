import freezegun
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    snapshot_clickhouse_queries,
)

from parameterized import parameterized
from rest_framework import status
from rest_framework.response import Response

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models import Organization, Team
from posthog.models.event.util import format_clickhouse_timestamp

INSERT_SINGLE_HEATMAP_EVENT = """
INSERT INTO sharded_heatmaps (
    session_id,
    team_id,
    distinct_id,
    timestamp,
    x,
    y,
    scale_factor,
    viewport_width,
    viewport_height,
    pointer_target_fixed,
    current_url,
    type
)
SELECT
    %(session_id)s,
    %(team_id)s,
    %(distinct_id)s,
    %(timestamp)s,
    %(x)s,
    %(y)s,
    %(scale_factor)s,
    %(viewport_width)s,
    %(viewport_height)s,
    %(pointer_target_fixed)s,
    %(current_url)s,
    %(type)s
"""


class TestSessionRecordings(APIBaseTest, ClickhouseTestMixin, QueryMatchingTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _assert_heatmap_no_result_count(
        self, params: dict[str, str | int | None] | None, expected_status_code: int = status.HTTP_200_OK
    ) -> None:
        response = self._get_heatmap(params, expected_status_code)
        if response.status_code == status.HTTP_200_OK:
            assert len(response.data["results"]) == 0

    def _assert_heatmap_result_count(self, params: dict[str, str | int | None] | None, expected_count: int) -> None:
        response = self._get_heatmap(params)
        assert len(response.data["results"]) == expected_count

    def _assert_heatmap_single_result_count(
        self, params: dict[str, str | int | None] | None, expected_grouped_count: int
    ) -> None:
        response = self._get_heatmap(params)
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["count"] == expected_grouped_count

    def _get_heatmap(
        self, params: dict[str, str | int | None] | None, expected_status_code: int = status.HTTP_200_OK
    ) -> Response:
        if params is None:
            params = {}

        query_params = "&".join([f"{key}={value}" for key, value in params.items()])
        response = self.client.get(f"/api/heatmap/?{query_params}")
        assert response.status_code == expected_status_code, response.data

        return response

    def _create_heatmap_event(
        self,
        session_id: str,
        type: str,
        date_from: str = "2023-03-08T09:00:00",
        viewport_width: int = 100,
        viewport_height: int = 100,
        x: int = 10,
        y: int = 20,
        current_url: str | None = None,
        distinct_id: str = "user_distinct_id",
        team_id: int | None = None,
        pointer_target_fixed: bool = True,
    ) -> None:
        if team_id is None:
            team_id = self.team.pk

        p = ClickhouseProducer()
        # because this is in a test it will write directly using SQL not really with Kafka
        p.produce(
            topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
            sql=INSERT_SINGLE_HEATMAP_EVENT,
            data={
                "session_id": session_id,
                "team_id": team_id,
                "distinct_id": distinct_id,
                "timestamp": format_clickhouse_timestamp(date_from),
                "x": round(x / 16),
                "y": round(y / 16),
                "scale_factor": 16,
                # this adjustment is done at ingestion
                "viewport_width": round(viewport_width / 16),
                "viewport_height": round(viewport_height / 16),
                "type": type,
                "pointer_target_fixed": pointer_target_fixed,
                "current_url": current_url if current_url else "http://posthog.com",
            },
        )

    def create_event(
        self,
        timestamp: str,
        team: Team | None = None,
        event_name: str = "$pageview",
        properties: dict | None = None,
        distinct_id: str = "user_distinct_id",
        session_id: str = "12345",
    ):
        if team is None:
            team = self.team
        if properties is None:
            properties = {"$os": "Windows 95", "$current_url": "aloha.com/2"}

        properties["$session_id"] = session_id

        return _create_event(
            team=team,
            event=event_name,
            timestamp=timestamp,
            distinct_id=distinct_id,
            properties=properties,
        )

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_get_empty_response(self) -> None:
        response = self.client.get("/api/heatmap/?date_from=2024-05-03")
        assert response.status_code == 200
        self.assertEqual(
            response.data,
            {
                "results": [],
                "fold": {
                    "total_count": 0,
                    "below_fold_count": 0,
                    "pct_below_fold": 0.0,
                    "median_viewport_height": None,
                },
                "has_more": False,
            },
        )

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_get_all_data_response(self) -> None:
        self._create_heatmap_event("session_1", "click")
        self._create_heatmap_event("session_2", "click")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 2)

    @freezegun.freeze_time("2025-03-31")
    def test_returns_below_the_fold_summary(self) -> None:
        # Non-fixed clicks against a 640px-tall viewport: one above the fold, two below it.
        self._create_heatmap_event("s1", "click", viewport_height=640, y=320, pointer_target_fixed=False)
        self._create_heatmap_event("s2", "click", viewport_height=640, y=960, pointer_target_fixed=False)
        self._create_heatmap_event("s3", "click", viewport_height=640, y=1280, pointer_target_fixed=False)
        # A fixed-position click below the fold is always on screen — excluded from the fold summary.
        self._create_heatmap_event("s4", "click", viewport_height=640, y=960, pointer_target_fixed=True)

        response = self.client.get("/api/heatmap/?date_from=2023-03-08&type=click")
        assert response.status_code == 200
        assert response.data["fold"] == {
            "total_count": 3,
            "below_fold_count": 2,
            "pct_below_fold": 66.7,
            "median_viewport_height": 640,
        }

    @freezegun.freeze_time("2025-03-31")
    def test_cannot_query_across_teams(self) -> None:
        self._create_heatmap_event("session_1", "click")
        self._create_heatmap_event("session_2", "click")

        org = Organization.objects.create(name="Separate Org")
        other_team = Team.objects.create(organization=org, name="other orgs team")
        self._create_heatmap_event("session_1", "click", team_id=other_team.pk)

        # second team's click is not counted
        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 2)

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_get_filter_by_date_from(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-07T07:00:00")
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 1)

    @snapshot_clickhouse_queries
    @freezegun.freeze_time("2023-03-15T09:00:00")
    def test_can_get_filter_by_relative_date(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-07T07:00:00")
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00")

        self._assert_heatmap_single_result_count({"date_from": "-7d", "date_to": "-1d"}, 1)
        self._assert_heatmap_no_result_count({"date_from": "dStart", "date_to": "dEnd"})

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_get_filter_by_click(self) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-08T07:00:00")
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:00:00")
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "type": "click"}, 1)

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "type": "rageclick"}, 2)

    def _create_three_distinct_points(self) -> None:
        # three distinct coordinates (differ by x) with counts 1, 2, 3 — created coolest-first so
        # insertion order is the reverse of count order, making the hottest-first assertions fail
        # if the query stops ordering by count.
        self._create_heatmap_event("s3", "click", "2023-03-08T08:00:00", x=80)
        for _ in range(2):
            self._create_heatmap_event("s2", "click", "2023-03-08T08:00:00", x=48)
        for _ in range(3):
            self._create_heatmap_event("s1", "click", "2023-03-08T08:00:00", x=16)

    @parameterized.expand(
        [
            ("default_returns_all", None, None, [3, 2, 1], False),
            ("limit_zero_is_unbounded", 0, None, [3, 2, 1], False),
            ("limit_truncates_hottest_first", 2, None, [3, 2], True),
            ("limit_equal_to_total", 3, None, [3, 2, 1], False),
            ("offset_pages_into_cooler_points", 2, 1, [2, 1], False),
            ("offset_past_end_returns_empty", 2, 5, [], False),
        ]
    )
    @freezegun.freeze_time("2025-03-31")
    def test_limit_and_offset_page_hottest_first(
        self, _name: str, limit: int | None, offset: int | None, expected_counts: list[int], expected_has_more: bool
    ) -> None:
        self._create_three_distinct_points()

        params: dict[str, str | int | None] = {"date_from": "2023-03-08", "type": "click"}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        response = self._get_heatmap(params)
        assert [r["count"] for r in response.data["results"]] == expected_counts
        assert response.data["has_more"] is expected_has_more

    @freezegun.freeze_time("2025-03-31")
    def test_scrolldepth_ignores_limit_and_has_no_has_more(self) -> None:
        for i, y in enumerate([100, 200, 300, 400]):
            self._create_heatmap_event(f"session_{i}", "scrolldepth", "2023-03-08T08:00:00", y=y, viewport_height=1000)

        response = self._get_heatmap({"date_from": "2023-03-08", "type": "scrolldepth", "limit": 1})
        assert len(response.data["results"]) > 1
        assert "has_more" not in response.data

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_filter_by_exact_url(self) -> None:
        self._create_heatmap_event("session_1", "rageclick", "2023-03-08T08:00:00", current_url="http://example.com")
        self._create_heatmap_event(
            "session_2", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/about"
        )
        self._create_heatmap_event(
            "session_3", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/about"
        )

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_exact": "http://example.com", "type": "rageclick"}, 1
        )

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_exact": "http://example.com/about", "type": "rageclick"}, 2
        )

    @parameterized.expand(
        [
            ("query_no_slash_data_no_slash", "http://example.com", "http://example.com"),
            ("query_no_slash_data_with_slash", "http://example.com", "http://example.com/"),
            ("query_with_slash_data_no_slash", "http://example.com/", "http://example.com"),
            ("query_with_slash_data_with_slash", "http://example.com/", "http://example.com/"),
        ]
    )
    @freezegun.freeze_time("2025-03-31")
    def test_url_exact_normalizes_trailing_slash(self, _name: str, query_url: str, data_url: str) -> None:
        self._create_heatmap_event("session_1", "click", "2023-03-08T08:00:00", current_url=data_url)

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_exact": query_url, "type": "click"}, 1
        )

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_filter_by_url_pattern_where_end_is_anchored(self) -> None:
        # home page with no trailing slash
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com")

        # home page with trailing slash
        self._create_heatmap_event(
            "session_1",
            "rageclick",
            "2023-03-08T08:00:00",
            current_url="http://example.com/",
        )

        # should match nothing, no trailing slash
        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_pattern": "http://example.com", "type": "rageclick"}, 1
        )

    @parameterized.expand(
        [
            ["http://example.com*", 6],
            ["http://example.com/products*", 5],
            ["http://example.com/products/1*", 2],
            ["http://example.com/products/*/reviews/*", 2],
            ["http://example.com/products/*/parts/*", 2],
            ["http://example.com/products/1*/parts/*", 1],
        ],
        name_func=lambda f, n, p: f"{f.__name__}_{p.args[0]}",
    )
    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_filter_by_url_pattern(self, pattern: str, expected_matches: int) -> None:
        # the home page
        self._create_heatmap_event("session_2", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/")

        # a product page with a review
        self._create_heatmap_event(
            "session_1",
            "rageclick",
            "2023-03-08T08:00:00",
            current_url="http://example.com/products/12345/reviews/4567",
        )

        # a different product page with a review
        self._create_heatmap_event(
            "session_1", "rageclick", "2023-03-08T08:00:00", current_url="http://example.com/products/3456/reviews/defg"
        )

        # all reviews for one product
        self._create_heatmap_event(
            "session_1", "rageclick", "2023-03-08T08:00:00", current_url="http://example.com/products/3456/reviews/"
        )

        # the same product but a different sub-route
        self._create_heatmap_event(
            "session_3", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/products/12345/parts/abcd"
        )

        # a different product that shares a part
        self._create_heatmap_event(
            "session_3", "rageclick", "2023-03-08T08:01:00", current_url="http://example.com/products/3456/parts/abcd"
        )

        # should match nothing, no trailing slash
        self._assert_heatmap_no_result_count(
            {"date_from": "2023-03-08", "url_pattern": "http://example.com", "type": "rageclick"}
        )

        self._assert_heatmap_single_result_count(
            {"date_from": "2023-03-08", "url_pattern": pattern, "type": "rageclick"},
            expected_matches,
        )

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_get_scrolldepth_counts(self) -> None:
        # to calculate expected scroll depth bucket from y and viewport height
        # ((round(y/16) + round(viewport_height/16)) * 16 // 100) * 100

        # scroll depth bucket 1000
        self._create_heatmap_event("session_1", "scrolldepth", "2023-03-08T07:00:00", y=10, viewport_height=1000)
        self._create_heatmap_event("session_2", "scrolldepth", "2023-03-08T08:00:00", y=100, viewport_height=1000)
        # scroll depth bucket 1100
        self._create_heatmap_event("session_3", "scrolldepth", "2023-03-08T08:01:00", y=200, viewport_height=1000)
        # scroll depth bucket 1200
        self._create_heatmap_event("session_4", "scrolldepth", "2023-03-08T08:01:00", y=300, viewport_height=1000)
        # scroll depth bucket 1300
        self._create_heatmap_event("session_5", "scrolldepth", "2023-03-08T08:01:00", y=400, viewport_height=1000)
        # scroll depth bucket 1400
        self._create_heatmap_event("session_6", "scrolldepth", "2023-03-08T08:01:00", y=500, viewport_height=1000)
        # scroll depth bucket 1800
        self._create_heatmap_event("session_7", "scrolldepth", "2023-03-08T08:01:00", y=900, viewport_height=1000)
        self._create_heatmap_event("session_8", "scrolldepth", "2023-03-08T08:01:00", y=900, viewport_height=1000)

        scroll_response = self._get_heatmap({"date_from": "2023-03-06", "type": "scrolldepth"})

        assert scroll_response.data == {
            "results": [
                {
                    "bucket_count": 2,
                    "cumulative_count": 8,
                    "scroll_depth_bucket": 1000,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 6,
                    "scroll_depth_bucket": 1100,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 5,
                    "scroll_depth_bucket": 1200,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 4,
                    "scroll_depth_bucket": 1300,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 3,
                    "scroll_depth_bucket": 1400,
                },
                {
                    "bucket_count": 2,
                    "cumulative_count": 2,
                    "scroll_depth_bucket": 1800,
                },
            ],
        }

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_get_scrolldepth_counts_by_visitor(self) -> None:
        # scroll depth bucket 1000
        self._create_heatmap_event(
            "session_1", "scrolldepth", "2023-03-08T07:00:00", y=100, viewport_height=1000, distinct_id="12345"
        )

        # one person only scrolls a little way
        # scroll depth bucket 1000
        self._create_heatmap_event(
            "session_2", "scrolldepth", "2023-03-08T08:00:00", y=100, viewport_height=1000, distinct_id="34567"
        )

        # the first person scrolls further
        # scroll depth bucket 1100
        self._create_heatmap_event(
            "session_3", "scrolldepth", "2023-03-08T08:01:00", y=200, viewport_height=1000, distinct_id="12345"
        )

        scroll_response = self._get_heatmap(
            {"date_from": "2023-03-06", "type": "scrolldepth", "aggregation": "unique_visitors"}
        )

        assert scroll_response.data == {
            "results": [
                {
                    "bucket_count": 2,
                    "cumulative_count": 3,
                    "scroll_depth_bucket": 1000,
                },
                {
                    "bucket_count": 1,
                    "cumulative_count": 1,
                    "scroll_depth_bucket": 1100,
                },
            ],
        }

    @staticmethod
    def heatmap_result(relative_x: float, count: int) -> dict:
        return {
            "count": count,
            "pointer_relative_x": relative_x,
            "pointer_target_fixed": True,
            "pointer_y": 16,
        }

    @parameterized.expand(
        [
            [
                "min_150",
                {"date_from": "2023-03-08", "viewport_width_min": "150"},
                [heatmap_result(0.08, 1), heatmap_result(0.09, 1), heatmap_result(0.1, 2), heatmap_result(0.11, 2)],
            ],
            [
                "min_161",
                {"date_from": "2023-03-08", "viewport_width_min": "161"},
                [
                    heatmap_result(0.08, 1),
                    heatmap_result(0.09, 1),
                    heatmap_result(0.1, 2),
                ],
            ],
            [
                "min_177",
                {"date_from": "2023-03-08", "viewport_width_min": "177"},
                [
                    heatmap_result(0.08, 1),
                    heatmap_result(0.09, 1),
                ],
            ],
            ["min_201", {"date_from": "2023-03-08", "viewport_width_min": "201"}, []],
            [
                "min_161_and_max_192",
                {"date_from": "2023-03-08", "viewport_width_min": 161, "viewport_width_max": 192},
                [heatmap_result(0.08, 1), heatmap_result(0.09, 1), heatmap_result(0.1, 2)],
            ],
        ]
    )
    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_filter_by_viewport(self, _name: str, query_params: dict, expected_results: list) -> None:
        # all these xs = round(10/16) = 1

        # viewport widths that scale to 9
        self._create_heatmap_event("session_1", "click", "2023-03-08T08:00:00", 150)
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00", 151)

        # viewport widths that scale to 10
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 152)
        self._create_heatmap_event("session_4", "click", "2023-03-08T08:01:00", 161)

        # viewport width that scales to 11
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 177)
        # viewport width that scales to 12
        self._create_heatmap_event("session_3", "click", "2023-03-08T08:01:00", 193)

        response = self._get_heatmap(query_params)
        assert sorted(response.data["results"], key=lambda k: k["pointer_relative_x"]) == expected_results

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_filter_by_test_accounts(self) -> None:
        self.team.test_account_filters = [
            {
                "key": "$host",
                "value": "127.0.0.1",
                "operator": "not_icontains",
                "type": "event",
            }
        ]
        self.team.save()

        self._create_heatmap_event("session_1", "click", "2023-03-08T08:00:00", viewport_width=100, x=5, y=10)
        self._create_heatmap_event("session_2", "click", "2023-03-08T08:00:00", viewport_width=100, x=5, y=10)
        self._create_heatmap_event(
            "session_3", "click", "2023-03-08T08:01:00", viewport_width=100, viewport_height=100, x=100, y=10
        )

        # 127.0.0.1 is a test account
        # so only session_3 should be included
        self.create_event(
            session_id="session_1",
            timestamp="2023-03-08T08:00:00",
            distinct_id="12345",
            properties={"$host": "127.0.0.1"},
        )
        self.create_event(
            session_id="session_2",
            timestamp="2023-03-08T08:00:00",
            distinct_id="12345",
            properties={"$host": "127.0.0.1"},
        )
        self.create_event(
            session_id="session_3",
            timestamp="2023-03-08T08:01:00",
            distinct_id="12345",
            properties={"$host": "posthog.com"},
        )

        response = self._get_heatmap({"date_from": "2023-03-08", "filter_test_accounts": True})
        json_results = response.data["results"]
        assert sorted(json_results, key=lambda k: k["pointer_relative_x"]) == [
            {
                "count": 1,
                "pointer_relative_x": 1.0,
                "pointer_target_fixed": True,
                "pointer_y": 16,
            },
        ]

        response_without_internal_filter = self._get_heatmap({"date_from": "2023-03-08"})
        json_results_two = response_without_internal_filter.data["results"]
        assert sorted(json_results_two, key=lambda k: k["pointer_relative_x"]) == [
            {
                "count": 2,
                "pointer_relative_x": 0.0,
                "pointer_target_fixed": True,
                "pointer_y": 16,
            },
            {
                "count": 1,
                "pointer_relative_x": 1.0,
                "pointer_target_fixed": True,
                "pointer_y": 16,
            },
        ]

    @parameterized.expand(
        [
            ("explicit_same_day", {"date_from": "2023-03-08", "date_to": "2023-03-08"}),
            ("relative_today", {"date_from": "dStart"}),
            ("relative_today_start_end", {"date_from": "dStart", "date_to": "dEnd"}),
        ]
    )
    @freezegun.freeze_time("2023-03-08T13:00:00")
    def test_filter_test_accounts_returns_data_for_single_day_range(self, _name: str, params: dict[str, str]) -> None:
        # A single-day window (date_from and date_to on the same day) must still return data when filtering
        # test accounts. The events subquery backing the test-account filter used to collapse to an impossible
        # range for same-day windows, hiding the whole heatmap.
        self.team.test_account_filters = [
            {
                "key": "$host",
                "value": "127.0.0.1",
                "operator": "not_icontains",
                "type": "event",
            }
        ]
        self.team.save()

        self._create_heatmap_event("session_1", "click", "2023-03-08T09:00:00", viewport_width=100, x=5, y=10)
        self.create_event(
            session_id="session_1",
            timestamp="2023-03-08T09:00:00",
            distinct_id="12345",
            properties={"$host": "posthog.com"},
        )

        response = self._get_heatmap({**params, "filter_test_accounts": True})
        assert response.data["results"] == [
            {
                "count": 1,
                "pointer_relative_x": 0.0,
                "pointer_target_fixed": True,
                "pointer_y": 16,
            },
        ]

    @freezegun.freeze_time("2025-03-31")
    @snapshot_clickhouse_queries
    def test_can_get_count_by_aggregation(self) -> None:
        # 3 items but 2 visitors
        self._create_heatmap_event("session_1", "click", distinct_id="12345")
        self._create_heatmap_event("session_2", "click", distinct_id="12345")
        self._create_heatmap_event("session_3", "click", distinct_id="54321")

        self._assert_heatmap_single_result_count({"date_from": "2023-03-08"}, 3)
        self._assert_heatmap_single_result_count({"date_from": "2023-03-08", "aggregation": "unique_visitors"}, 2)

    @parameterized.expand(
        [
            ("boolean_true_is_valid", True, status.HTTP_200_OK),
            ("boolean_false_is_valid", False, status.HTTP_200_OK),
            ("none_is_invalid", None, status.HTTP_400_BAD_REQUEST),
            ("empty_string_is_valid_because_it_is_none", "", status.HTTP_200_OK),
            ("whitespace_string_is_invalid", "     ", status.HTTP_400_BAD_REQUEST),
            ("number_one_is_valid", 1, status.HTTP_200_OK),
            ("number_zero_is_valid", 0, status.HTTP_200_OK),
            ("dict_is_invalid", {"test": "test"}, status.HTTP_400_BAD_REQUEST),
            ("dict_with_filter_key_is_invalid", {"filterTestAccounts": "test"}, status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_only_allow_valid_values_for_filter_test_accounts(
        self, _test_name: str, choice: str | None, expected_status_code: int
    ) -> None:
        self._assert_heatmap_no_result_count(
            {"date_from": "2023-03-08", "filter_test_accounts": choice}, expected_status_code=expected_status_code
        )

    @parameterized.expand(
        [
            ["total_count", status.HTTP_200_OK],
            ["unique_visitors", status.HTTP_200_OK],
            ["direction", status.HTTP_400_BAD_REQUEST],
            # equivalent to not providing it
            ["", status.HTTP_200_OK],
            ["     ", status.HTTP_400_BAD_REQUEST],
            [None, status.HTTP_400_BAD_REQUEST],
        ]
    )
    def test_only_allow_valid_values_for_aggregation(self, choice: str | None, expected_status_code: int) -> None:
        self._assert_heatmap_no_result_count(
            {"date_from": "2023-03-08", "aggregation": choice}, expected_status_code=expected_status_code
        )

    @parameterized.expand(
        [
            ("explicit_true", {"date_from": "2023-03-08", "hide_zero_coordinates": "true"}),
            ("default", {"date_from": "2023-03-08"}),
        ]
    )
    @freezegun.freeze_time("2025-03-31")
    def test_hide_zero_coordinates_filters_out_zero_zero_events(self, _name: str, params: dict) -> None:
        self._create_heatmap_event("session_1", "click", x=0, y=0)
        self._create_heatmap_event("session_2", "click", x=10, y=20)

        self._assert_heatmap_single_result_count(params, 1)

    @freezegun.freeze_time("2025-03-31")
    def test_hide_zero_coordinates_false_includes_zero_zero(self) -> None:
        self._create_heatmap_event("session_1", "click", x=0, y=0)
        self._create_heatmap_event("session_2", "click", x=10, y=20)

        self._assert_heatmap_result_count({"date_from": "2023-03-08", "hide_zero_coordinates": "false"}, 2)

    @freezegun.freeze_time("2025-03-31")
    def test_hide_zero_coordinates_not_applied_to_scrolldepth(self) -> None:
        self._create_heatmap_event("session_1", "scrolldepth", x=0, y=0)

        self._assert_heatmap_result_count({"date_from": "2023-03-08", "type": "scrolldepth"}, 1)
