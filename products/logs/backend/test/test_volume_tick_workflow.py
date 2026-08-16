import json
import uuid
import secrets
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.clickhouse.client import sync_execute

from products.logs.backend.temporal.volume_tick.activities import (
    VolumeTickInput,
    VolumeTickOutput,
    count_teams_with_logs,
    due_bucket_bounds,
)
from products.logs.backend.temporal.volume_tick.constants import BUCKET_MINUTES, WORKFLOW_NAME
from products.logs.backend.temporal.volume_tick.workflow import LogsVolumeTickWorkflow

TASK_QUEUE = "logs-volume-tick-test"


@pytest.mark.asyncio
async def test_schedule_shaped_invocation_runs_the_tick() -> None:
    # Invoke by workflow name with an asdict payload — the exact contract the
    # Temporal schedule uses — so a rename or input-shape drift fails here. The
    # activity is faked: the real one needs ClickHouse, and this test pins the
    # plumbing, not the query.
    @activity.defn(name="volume_tick_heartbeat_activity")
    async def fake_heartbeat(_input: VolumeTickInput) -> VolumeTickOutput:
        return VolumeTickOutput(
            ticked_at="2026-08-12T00:16:00+00:00",
            teams_with_logs=3,
            minute_shard=1,
            teams_due_in_shard=1,
            due_bucket_start="2026-08-12T00:00:00+00:00",
            due_bucket_end="2026-08-12T00:05:00+00:00",
        )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[LogsVolumeTickWorkflow],
            activities=[fake_heartbeat],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                WORKFLOW_NAME,
                asdict(VolumeTickInput()),
                id=f"test-volume-tick-{uuid.uuid4()}",
                task_queue=TASK_QUEUE,
            )

    assert result["teams_with_logs"] == 3


class TestDueBucketBounds(SimpleTestCase):
    @parameterized.expand(
        [
            # 10:16:30 - 10min allowance = 10:06:30; newest closed grid end is 10:05.
            ("mid_window", datetime(2026, 8, 12, 10, 16, 30, tzinfo=UTC), datetime(2026, 8, 12, 10, 0, tzinfo=UTC)),
            # Exactly on the boundary: at 10:20:00 the 10:05-10:10 bucket becomes due.
            ("on_the_boundary", datetime(2026, 8, 12, 10, 20, 0, tzinfo=UTC), datetime(2026, 8, 12, 10, 5, tzinfo=UTC)),
            # One second before the boundary, the previous bucket is still the due one.
            (
                "second_before_boundary",
                datetime(2026, 8, 12, 10, 19, 59, tzinfo=UTC),
                datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
            ),
            # Day boundary: just past midnight, the due bucket is yesterday's 23:45-23:50.
            ("day_rollover", datetime(2026, 8, 13, 0, 0, 30, tzinfo=UTC), datetime(2026, 8, 12, 23, 45, tzinfo=UTC)),
        ]
    )
    def test_due_bucket_bounds(self, _name: str, now: datetime, expected_start: datetime) -> None:
        due = due_bucket_bounds(now)
        assert due.start == expected_start
        assert due.end == expected_start + timedelta(minutes=5)


class TestCountTeamsWithLogs(ClickhouseTestMixin, BaseTest):
    # The test ClickHouse keeps rows across runs and Postgres team ids repeat per
    # run, so neither a fixed window nor self.team gives isolation. Random team
    # ids plus delta assertions stay exact under any accumulated data.
    WINDOW_START = datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
    WINDOW_END = WINDOW_START + timedelta(minutes=5)

    def _insert_log_rows(self, rows: list[tuple[int, datetime]]) -> None:
        payload = [
            {
                "uuid": str(uuid.uuid4()),
                "team_id": team_id,
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S.%f"),
                "body": "volume tick test",
                "severity_text": "info",
                "severity_number": 9,
                "service_name": "svc",
                "resource_attributes": {},
                "attributes_map_str": {},
            }
            for team_id, ts in rows
        ]
        # Foreground insert: the async distributed-insert queue would race the
        # SELECT below and make the count flaky.
        sync_execute(
            "INSERT INTO logs_distributed FORMAT JSONEachRow\n" + "\n".join(json.dumps(r) for r in payload),
            settings={"distributed_foreground_insert": 1},
        )

    def test_counts_distinct_teams_inside_the_half_open_window(self) -> None:
        inside = self.WINDOW_START + timedelta(minutes=1)
        # Residue-controlled ids: team_a lands in shard 1, team_b in shard 2, so
        # the shard subset is exact regardless of what the random base is.
        base = (secrets.randbelow(2**27) + 1) * BUCKET_MINUTES
        team_a, team_b, team_c = base + 1, base + 2, base + 3
        before = count_teams_with_logs(self.WINDOW_START, self.WINDOW_END, shard=1)

        self._insert_log_rows(
            [
                (team_a, inside),
                (team_a, inside + timedelta(seconds=30)),
                (team_b, self.WINDOW_START),
                (team_c, self.WINDOW_START - timedelta(seconds=1)),
                (team_c, self.WINDOW_END),
            ]
        )

        after = count_teams_with_logs(self.WINDOW_START, self.WINDOW_END, shard=1)
        # +2, not +3: team_a counts once despite two rows, and team_c's rows sit
        # exactly on the outside of both half-open window edges.
        assert after.total == before.total + 2
        # Only team_a's residue matches shard 1; team_b is in the window but in shard 2.
        assert after.due_in_shard == before.due_in_shard + 1
