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
from products.growth.backend.temporal.signup_enrichment.sweep_types import SweepInputs, SweepKind


def _action() -> ScheduleActionStartWorkflow:
    action = build_icp_reenrichment_sweep_schedule().action
    assert isinstance(action, ScheduleActionStartWorkflow)
    return action


class TestIcpReenrichmentSweepSchedule:
    def test_targets_the_signup_enrichment_queue(self) -> None:
        assert _action().task_queue == settings.SIGNUP_ENRICHMENT_TASK_QUEUE

    def test_starts_the_generic_sweep_as_reenrichment_under_a_stable_id(self) -> None:
        assert _action().workflow == "growth-enrichment-sweep"
        assert _action().args == [SweepInputs(kind=SweepKind.ICP_REENRICHMENT, cap=None)]
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

    def test_starts_the_generic_sweep_as_status_poll_under_a_stable_id(self) -> None:
        assert _poll_action().workflow == "growth-enrichment-sweep"
        assert _poll_action().args == [SweepInputs(kind=SweepKind.HARMONIC_STATUS_POLL, cap=None)]
        assert _poll_action().id == HARMONIC_STATUS_POLL_SCHEDULE_ID

    def test_skips_an_overlapping_run_and_fires_daily_an_hour_before_the_sweep(self) -> None:
        schedule = build_harmonic_status_poll_schedule()
        assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert schedule.spec.cron_expressions == [HARMONIC_STATUS_POLL_CRON]
        assert HARMONIC_STATUS_POLL_CRON == "40 6 * * *"
        assert CRON == "40 7 * * *"
