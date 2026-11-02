import datetime as dt

import time_machine
from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from products.growth.backend.constants import TEAM_SDK_CACHE_EXPIRY
from products.growth.backend.models import SdkVersionsDaily
from products.growth.backend.team_sdk_versions import get_and_cache_team_sdk_versions, get_sdk_versions_for_team


class TestGetSdkVersionsForTeam(SimpleTestCase):
    @parameterized.expand(
        [
            ("posthog-server",),
            ("posthog-unity",),
            ("posthog-node-mcp",),
            ("posthog-python-mcp",),
            ("posthog-edge",),
            ("posthog-convex",),
            ("posthog-rails",),
            ("posthog-aspnetcore",),
            ("posthog-rs",),
            ("posthog-rs-mcp",),
            ("posthog-godot",),
            ("posthog-unreal",),
            ("posthog-go-mcp",),
            ("posthog-ruby-mcp",),
            ("js",),
        ]
    )
    @patch("products.growth.backend.team_sdk_versions.sdk_versions_window", return_value=None)
    @patch("products.growth.backend.team_sdk_versions.run_query")
    @patch("products.growth.backend.team_sdk_versions.Team.objects.get")
    def test_sorts_partial_and_full_semver_versions_consistently(
        self, sdk_type: str, mock_team_get: MagicMock, mock_run_query: MagicMock, _mock_window: MagicMock
    ) -> None:
        mock_team_get.return_value = MagicMock()
        mock_run_query.return_value = MagicMock(
            results=[
                (sdk_type, "1.2.0", dt.datetime(2026, 7, 14, tzinfo=dt.UTC), 100),
                (sdk_type, "1.10", dt.datetime(2026, 7, 14, tzinfo=dt.UTC), 50),
            ]
        )

        result = get_sdk_versions_for_team(team_id=1)

        assert result is not None
        assert [entry["lib_version"] for entry in result[sdk_type]] == ["1.10", "1.2.0"]


class TestGetAndCacheTeamSdkVersions(SimpleTestCase):
    @patch("products.growth.backend.team_sdk_versions.get_sdk_versions_for_team")
    def test_uses_team_sdk_cache_expiry(self, mock_get_sdk_versions: MagicMock):
        mock_get_sdk_versions.return_value = {"web": [{"lib_version": "1.0.0", "max_timestamp": "x", "count": 1}]}
        mock_redis = MagicMock()

        get_and_cache_team_sdk_versions(team_id=1, redis_client=mock_redis)

        mock_redis.setex.assert_called_once()
        key, ttl, _payload = mock_redis.setex.call_args[0]
        assert key == "sdk_versions:team:v3:1"
        assert ttl == TEAM_SDK_CACHE_EXPIRY


@time_machine.travel("2026-10-29T12:00:00Z", tick=False)
class TestSdkVersionsFromRollup(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _publish(self, days_ago: range, version: str, count_per_day: int) -> None:
        today = dt.datetime.now(dt.UTC).date()
        SdkVersionsDaily.objects.unscoped().bulk_create(
            SdkVersionsDaily(
                team_id=self.team.id,
                day=today - dt.timedelta(days=offset),
                lib="web",
                lib_version=version,
                event_count=count_per_day,
                max_timestamp=dt.datetime.combine(today - dt.timedelta(days=offset), dt.time(12), tzinfo=dt.UTC),
            )
            for offset in days_ago
        )

    def _web_event(self, version: str, timestamp: dt.datetime) -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="user",
            timestamp=timestamp,
            properties={"$lib": "web", "$lib_version": version},
        )
        flush_persons_and_events()

    def test_sums_the_rollup_week_and_adds_events_since_it_ended(self) -> None:
        self.team.timezone = "America/Phoenix"
        self.team.save()
        self._publish(range(1, 8), "1.0.0", count_per_day=10)
        self._publish(range(8, 9), "0.9.0", count_per_day=10)
        self._web_event("1.1.0", dt.datetime.now(dt.UTC))
        self._web_event("1.0.0", dt.datetime.now(dt.UTC))

        result = get_sdk_versions_for_team(self.team.id)

        assert result is not None
        assert [(entry["lib_version"], entry["count"], entry["max_timestamp"]) for entry in result["web"]] == [
            ("1.1.0", 1, "2026-10-29 12:00:00+00:00"),
            ("1.0.0", 71, "2026-10-29 12:00:00+00:00"),
        ]

    def test_falls_back_to_raw_events_when_the_rollup_is_stale(self) -> None:
        self._publish(range(3, 10), "1.0.0", count_per_day=10)
        self._web_event("2.0.0", dt.datetime.now(dt.UTC) - dt.timedelta(days=2))

        result = get_sdk_versions_for_team(self.team.id)

        assert result is not None
        assert [(entry["lib_version"], entry["count"]) for entry in result["web"]] == [("2.0.0", 1)]

    def test_reads_every_live_version_past_the_default_hogql_row_limit(self) -> None:
        for patch_version in range(150):
            _create_event(
                team=self.team,
                event="$pageview",
                distinct_id="user",
                timestamp=dt.datetime.now(dt.UTC),
                properties={"$lib": "web", "$lib_version": f"1.0.{patch_version}"},
            )
        flush_persons_and_events()

        result = get_sdk_versions_for_team(self.team.id)

        assert result is not None
        assert len(result["web"]) == 150
