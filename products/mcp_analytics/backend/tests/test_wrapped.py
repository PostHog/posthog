import json
from io import StringIO

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, flush_persons_and_events
from unittest.mock import patch

from django.core.management import CommandError, call_command

from products.mcp_analytics.backend.models import MCPAnalyticsWrapped
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin
from products.mcp_analytics.backend.tests.test_wrapped_queries import CLAUDE, NOW, _WrappedEventsTestMixin
from products.mcp_analytics.backend.wrapped.generate import compute_wrapped, generate_wrapped_snapshot


@time_machine.travel(NOW, tick=False)
class TestWrappedSnapshot(_WrappedEventsTestMixin, _MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def test_snapshot_is_stored_ready_and_a_rerun_replaces_it(self) -> None:
        self._seed_year()

        first = generate_wrapped_snapshot(self.team, 2026)
        second = generate_wrapped_snapshot(self.team, 2026)

        assert first.id == second.id
        second.refresh_from_db()
        assert second.status == MCPAnalyticsWrapped.Status.READY
        cards = second.payload
        assert set(cards) == {
            "intro",
            "tool_calls",
            "top_tools",
            "apps",
            "labs",
            "models",
            "rush_hour",
            "reliability",
            "speed",
            "archetype",
        }
        assert cards["intro"] == {"tracked_since": "2026-07", "server_count": 1}
        assert cards["top_tools"]["tools"] == [
            {"tool": "get_forecast", "calls": 270},
            {"tool": "list_alerts", "calls": 40},
            {"tool": "create_alert", "calls": 30},
        ]
        assert cards["models"]["shares"][0] == {"label": "Claude Sonnet", "share": 0.8904}

    def test_project_below_the_bar_is_ineligible_without_the_properties_scan(self) -> None:
        self._emit("2026-08-11T23:30:00Z", "get_forecast", 150, **CLAUDE)
        flush_persons_and_events()

        with patch("products.mcp_analytics.backend.wrapped.generate.fetch_wrapped_aggregates") as aggregates:
            snapshot = generate_wrapped_snapshot(self.team, 2026)

        aggregates.assert_not_called()
        assert snapshot.status == MCPAnalyticsWrapped.Status.INELIGIBLE
        assert snapshot.payload == {}

    def test_a_failed_rerun_keeps_the_ready_snapshot(self) -> None:
        self._seed_year()
        generate_wrapped_snapshot(self.team, 2026)

        with patch(
            "products.mcp_analytics.backend.wrapped.generate.fetch_wrapped_aggregates",
            side_effect=RuntimeError("ClickHouse went away"),
        ):
            with self.assertRaises(RuntimeError):
                generate_wrapped_snapshot(self.team, 2026)

        snapshot = MCPAnalyticsWrapped.objects.get(team=self.team, year=2026)
        assert snapshot.status == MCPAnalyticsWrapped.Status.READY
        assert snapshot.payload["tool_calls"]["total_calls"] == 365

    def test_dry_run_prints_the_payload_and_stores_nothing(self) -> None:
        self._seed_year()
        out = StringIO()

        call_command(
            "generate_mcp_analytics_wrapped", "--team-id", str(self.team.id), "--year", "2026", "--dry-run", stdout=out
        )

        printed = json.loads(out.getvalue())
        assert printed == json.loads(
            json.dumps({"status": "ready", "payload": compute_wrapped(self.team, 2026).payload})
        )
        assert not MCPAnalyticsWrapped.objects.filter(team=self.team).exists()

    def test_command_fails_for_a_missing_team(self) -> None:
        with self.assertRaises(CommandError):
            call_command("generate_mcp_analytics_wrapped", "--team-id", "999999999", "--year", "2026")
