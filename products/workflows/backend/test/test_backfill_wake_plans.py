from io import StringIO
from typing import Optional

from posthog.test.base import BaseTest

from django.core.management import call_command

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow

CLOCK_CONDITION = "toUnixTimestamp(now()) >= toUnixTimestamp(toDateTime(person.properties.expires_at)) - 86400"
WAREHOUSE_CONDITION = "dateDiff('day', now(), toDateTime(supabase_user_stats.trial_ends_at)) <= 2"


def wait_action(action_id: str, hogql: Optional[str]) -> dict:
    condition = {"filters": {"properties": [{"key": hogql, "type": "hogql", "value": None}]}} if hogql else None
    return {
        "id": action_id,
        "name": action_id,
        "type": "wait_until_condition",
        "config": {"condition": condition, "max_wait_duration": "20d"},
    }


class TestBackfillWakePlans(BaseTest):
    def _flow(self, actions: list[dict], status: str = "active") -> HogFlow:
        return HogFlow.objects.create(
            team=self.team, name="f", status=status, actions=actions, edges=[], trigger={"type": "event"}
        )

    def _run(self, *args: str) -> str:
        out = StringIO()
        call_command("backfill_wake_plans", *args, stdout=out)
        return out.getvalue()

    def _plan_of(self, flow: HogFlow, action_id: str) -> dict:
        flow.refresh_from_db()
        action = next(a for a in flow.actions if a["id"] == action_id)
        return action["config"].get("wake_plan")

    def test_dry_run_reports_verdicts_without_writing(self):
        # The review pass has to be trustworthy: it must classify correctly *and* leave the rows alone,
        # otherwise there is no safe way to inspect a backfill before committing to it.
        flow = self._flow([wait_action("w1", CLOCK_CONDITION)])

        output = self._run()

        assert "SCHEDULABLE" in output
        assert "dry run" in output
        assert self._plan_of(flow, "w1") is None

    def test_apply_stores_a_timer_for_a_clock_wait(self):
        flow = self._flow([wait_action("w1", CLOCK_CONDITION)])

        self._run("--apply")

        plan = self._plan_of(flow, "w1")
        assert plan["unsupported_reason"] is None
        assert len(plan["timers"]) == 1

    def test_warehouse_backed_wait_is_left_on_polling(self):
        # The case that motivated the runtime-roots check: invertible on paper, unevaluable at wake.
        # It must be recorded as polling rather than handed a timer that always resolves to null.
        flow = self._flow([wait_action("w1", WAREHOUSE_CONDITION)])

        output = self._run("--apply")

        assert "POLLING" in output
        plan = self._plan_of(flow, "w1")
        assert plan["unsupported_reason"] is not None
        assert plan["timers"] == []

    def test_is_idempotent(self):
        # Re-running must be a no-op, so the command is safe to schedule or repeat after a partial run.
        flow = self._flow([wait_action("w1", CLOCK_CONDITION)])
        self._run("--apply")
        first = self._plan_of(flow, "w1")

        output = self._run("--apply")

        assert "flows needing an update: 0" in output
        assert self._plan_of(flow, "w1") == first

    def test_skips_flows_that_are_not_active(self):
        flow = self._flow([wait_action("w1", CLOCK_CONDITION)], status="draft")

        self._run("--apply")

        assert self._plan_of(flow, "w1") is None
