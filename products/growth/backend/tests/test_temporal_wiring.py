from collections.abc import Callable
from typing import Any, cast

from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings
from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.client import ScheduleOverlapPolicy
from temporalio.common import WorkflowIDReusePolicy

from products.growth.backend.facade.temporal import ACTIVITIES, WORKFLOWS
from products.growth.backend.temporal.signup_enrichment import schedule
from products.growth.backend.temporal.signup_enrichment.harmonic_status_poll import HarmonicStatusPollInputs
from products.growth.backend.temporal.signup_enrichment.reenrichment import IcpReenrichmentSweepInputs
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_signup_enrichment
from products.growth.backend.temporal.signup_enrichment.workflow import SignupEnrichmentInputs


class TestSignupEnrichmentTemporalWiring(SimpleTestCase):
    def test_registers_workflows_by_name_in_order(self):
        assert [workflow._Definition.must_from_class(w).name for w in WORKFLOWS] == [
            "signup-enrichment",
            "signup-enrichment-recheck",
            "icp-reenrichment-sweep",
            "harmonic-enrichment-status-poll",
        ]

    def test_registers_activities_by_name_in_order(self):
        assert [activity._Definition.must_from_callable(cast(Callable[..., Any], a)).name for a in ACTIVITIES] == [
            "enrich_signup_organization_activity",
            "select_reenrichment_candidates_activity",
            "reenrich_organization_activity",
            "report_sweep_run_activity",
            "select_status_poll_candidates_activity",
            "poll_status_batch_activity",
            "report_status_poll_run_activity",
        ]

    def test_daily_schedules_keep_their_ids_and_crons(self):
        assert schedule.SCHEDULE_ID == "icp-reenrichment-sweep-daily"
        assert schedule.CRON == "40 7 * * *"
        assert schedule.HARMONIC_STATUS_POLL_SCHEDULE_ID == "harmonic-enrichment-status-poll-daily"
        assert schedule.HARMONIC_STATUS_POLL_CRON == "40 6 * * *"

    @parameterized.expand(
        [
            (
                "icp_reenrichment_sweep",
                schedule.build_icp_reenrichment_sweep_schedule,
                "icp-reenrichment-sweep",
                "icp-reenrichment-sweep-daily",
                [IcpReenrichmentSweepInputs()],
                ["40 7 * * *"],
            ),
            (
                "harmonic_status_poll",
                schedule.build_harmonic_status_poll_schedule,
                "harmonic-enrichment-status-poll",
                "harmonic-enrichment-status-poll-daily",
                [HarmonicStatusPollInputs()],
                ["40 6 * * *"],
            ),
        ]
    )
    def test_daily_schedule_starts_its_workflow_on_the_enrichment_queue_without_overlap(
        self, _name, build, workflow_name, schedule_id, args, cron_expressions
    ):
        built = build()

        assert built.action.workflow == workflow_name
        assert built.action.id == schedule_id
        assert built.action.args == args
        assert built.action.task_queue == settings.SIGNUP_ENRICHMENT_TASK_QUEUE
        assert built.spec.cron_expressions == cron_expressions
        assert built.policy.overlap is ScheduleOverlapPolicy.SKIP

    def test_dispatch_starts_the_signup_workflow_under_the_organization_id(self):
        inputs = SignupEnrichmentInputs(organization_id="org-1", distinct_id="d", domain="acme.com")
        client = MagicMock(start_workflow=AsyncMock())

        with patch("products.growth.backend.temporal.signup_enrichment.trigger.sync_connect", return_value=client):
            dispatch_signup_enrichment(inputs)

        client.start_workflow.assert_awaited_once_with(
            "signup-enrichment",
            inputs,
            id="signup-enrichment-org-1",
            task_queue=settings.SIGNUP_ENRICHMENT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
