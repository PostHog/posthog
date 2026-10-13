from django.conf import settings

from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

from products.growth.backend.temporal.signup_enrichment.schedule import (
    CRON,
    HARMONIC_STATUS_POLL_CRON,
    HARMONIC_STATUS_POLL_SCHEDULE_ID,
    SCHEDULE_ID,
    build_harmonic_status_poll_schedule,
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


def _poll_action() -> ScheduleActionStartWorkflow:
    action = build_harmonic_status_poll_schedule().action
    assert isinstance(action, ScheduleActionStartWorkflow)
    return action


class TestHarmonicStatusPollSchedule:
    def test_targets_the_signup_enrichment_queue(self) -> None:
        assert _poll_action().task_queue == settings.SIGNUP_ENRICHMENT_TASK_QUEUE

    def test_starts_the_poll_workflow_under_a_stable_id(self) -> None:
        assert _poll_action().workflow == "harmonic-enrichment-status-poll"
        assert _poll_action().id == HARMONIC_STATUS_POLL_SCHEDULE_ID

    def test_skips_an_overlapping_run_and_fires_daily_an_hour_before_the_sweep(self) -> None:
        schedule = build_harmonic_status_poll_schedule()
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert schedule.spec.cron_expressions == [HARMONIC_STATUS_POLL_CRON]
        assert HARMONIC_STATUS_POLL_CRON == "40 6 * * *"
        assert CRON == "40 7 * * *"
