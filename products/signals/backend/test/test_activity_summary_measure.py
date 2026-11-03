import json
import datetime
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import CommandError, call_command

from parameterized import parameterized

from posthog.models import ActivityLog

from products.signals.backend.activity_summary.measure import Coverage, coverage_report, measure_pair
from products.signals.backend.activity_summary.render import ACTIVITY_LINES, ActivityItem, TaskItem
from products.signals.backend.models import UserActivitySummary
from products.signals.backend.test.test_activity_summary_render import FakeLLM

NOW = datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC)
ANSWER = json.dumps(
    {
        "profile": "## Funnels\n- Builds the signup funnel.",
        "headline": "Builds the signup funnel.",
        "themes": [{"label": "Signup funnel", "mode": "building", "strength": "high", "refs": ["o1"]}],
        "modes": ["building"],
        "recent_shift": None,
    }
)
TASK = TaskItem(
    at=NOW - datetime.timedelta(days=1), title="why", summary="Goal: find why weekly signups dropped.", tags=()
)


def _change(name: str, client: str | None = None) -> ActivityItem:
    return ActivityItem(
        at=NOW - datetime.timedelta(days=1), scope="Insight", activity="created", name=name, client=client
    )


@parameterized.expand(
    [
        ("tasks only", [TASK], [], Coverage.TASKS_ONLY, False),
        ("activity only", [], [_change("Signup funnel")], Coverage.ACTIVITY_ONLY, False),
        ("both", [TASK], [_change("Signup funnel")], Coverage.BOTH, False),
        ("neither once the filters drop every row", [], [_change("Scout funnel", "scout:x")], Coverage.NEITHER, False),
        (
            "the activity line cap binds",
            [],
            [_change(f"Funnel {index}") for index in range(ACTIVITY_LINES + 1)],
            Coverage.ACTIVITY_ONLY,
            True,
        ),
    ]
)
def test_measure_pair_classifies_coverage(
    _name: str, tasks: list[TaskItem], activity: list[ActivityItem], coverage: Coverage, capped: bool
) -> None:
    pair = measure_pair(tasks, activity, as_of=NOW, seed=1)

    assert (pair.coverage, pair.activity_lines_capped) == (coverage, capped)
    report = coverage_report([pair], min_units=1)
    assert report.coverage[coverage] == 1
    assert report.caps["activity_lines"] == int(capped)


@time_machine.travel(NOW, tick=False)
class TestMeasureActivitySummarySources(BaseTest):
    def _log(self, name: str) -> None:
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            user=self.user,
            scope="Insight",
            activity="created",
            item_id=name,
            detail={"name": name},
            created_at=NOW - datetime.timedelta(days=1),
        )

    def _run(self, *args: str) -> str:
        out = StringIO()
        with patch("products.signals.backend.activity_summary.measure.list_user_task_times", return_value=[]):
            call_command("measure_activity_summary_sources", *args, stdout=out, stderr=StringIO())
        return out.getvalue()

    def test_coverage_prints_counts_without_rendered_text(self) -> None:
        self._log("Signup funnel")

        with patch("products.signals.backend.activity_summary.measure.user_tasks", return_value=[TASK]):
            out = self._run()

        assert "Signup funnel" not in out and "signups" not in out
        report = json.loads(out)
        assert (report["pairs"], report["coverage"][Coverage.BOTH]) == (1, 1)

    def test_leave_one_out_refuses_without_an_organization(self) -> None:
        with pytest.raises(CommandError):
            self._run("--mode", "leave-one-out")

    def test_leave_one_out_builds_one_variant_per_source_and_writes_no_summary(self) -> None:
        for index in range(3):
            self._log(f"Funnel {index}")
        llm = FakeLLM([ANSWER])

        with (
            TemporaryDirectory() as directory,
            patch("products.signals.backend.activity_summary.measure.user_tasks", return_value=[TASK]),
            patch("products.signals.backend.activity_summary.measure.gateway_client", return_value=llm),
        ):
            output = Path(directory) / "out.jsonl"
            totals = json.loads(
                self._run(
                    "--mode", "leave-one-out", "--organization-id", str(self.organization.id), "--output", str(output)
                )
            )
            records = [json.loads(line) for line in output.read_text().splitlines()]

        assert [(r["variant"], r["tasks"], r["activity_lines"]) for r in records] == [
            ("all", 1, 3),
            ("without_tasks", 0, 3),
            ("without_activity", 1, 0),
        ]
        assert len(llm.requests) == 3
        assert set(totals) == {"all", "without_tasks", "without_activity"}
        assert not UserActivitySummary.objects.for_team(self.team.id).exists()
