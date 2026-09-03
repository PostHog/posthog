from django.conf import settings

from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

from products.growth.backend.temporal.signup_enrichment.schedule import (
    CRON,
    SCHEDULE_ID,
    build_icp_reenrichment_sweep_schedule,
)


def _action() -> ScheduleActionStartWorkflow:
    action = build_icp_reenrichment_sweep_schedule().action
    assert isinstance(action, ScheduleActionStartWorkflow)
    return action


class TestIcpReenrichmentSweepSchedule:
    def test_targets_the_signup_enrichment_queue(self) -> None:
        assert _action().task_queue == settings.SIGNUP_ENRICHMENT_TASK_QUEUE

    def test_starts_the_sweep_workflow_under_a_stable_id(self) -> None:
        assert _action().workflow == "icp-reenrichment-sweep"
        assert _action().id == SCHEDULE_ID

    def test_skips_an_overlapping_run_and_fires_daily(self) -> None:
        schedule = build_icp_reenrichment_sweep_schedule()
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert schedule.spec.cron_expressions == [CRON]
