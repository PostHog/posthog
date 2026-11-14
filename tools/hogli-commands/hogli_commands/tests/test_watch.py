from __future__ import annotations

from dataclasses import replace

import pytest

from hogli_commands.watch import ClickHouseIdleStop, ClickHouseUsage


def _idle_usage(tick: int) -> ClickHouseUsage:
    # The watcher's own usage query adds one query per tick, so an idle ClickHouse counts up by one.
    return ClickHouseUsage(query_count=tick, client_connections=0, stack_running=False)


@pytest.mark.parametrize(
    "last_tick, expect_stop",
    [
        (_idle_usage(3), True),
        (replace(_idle_usage(3), stack_running=True), False),
        (replace(_idle_usage(3), client_connections=1), False),
        (replace(_idle_usage(3), query_count=1000), False),
    ],
    ids=["idle", "dev_stack_running", "client_connected", "new_queries"],
)
def test_clickhouse_idle_stop_only_after_a_full_unused_window(last_tick: ClickHouseUsage, expect_stop: bool) -> None:
    idle_stop = ClickHouseIdleStop(idle_minutes=30, now=0)
    assert idle_stop.observe(_idle_usage(1), now=0) is False
    assert idle_stop.observe(_idle_usage(2), now=29 * 60) is False
    # Any sign of use on the last tick of the window resets it, so the stop waits.
    assert idle_stop.observe(last_tick, now=30 * 60) is expect_stop
