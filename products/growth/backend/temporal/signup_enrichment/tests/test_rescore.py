import uuid

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

from asgiref.sync import async_to_sync
from temporalio import activity
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User

from products.growth.backend.enrichment.core import EnrichmentOutcome
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.models import OrganizationEnrichment
from products.growth.backend.temporal.signup_enrichment.rescore import (
    WizardStampRescoreInputs,
    WizardStampRescoreWorkflow,
    resolve_wizard_rescore_signup_inputs_activity,
)
from products.growth.backend.temporal.signup_enrichment.trigger import dispatch_wizard_stamp_rescore
from products.growth.backend.temporal.signup_enrichment.workflow import enrich_signup_organization_activity

_TRIGGER_MODULE = "products.growth.backend.temporal.signup_enrichment.trigger"
_WORKFLOW_MODULE = "products.growth.backend.temporal.signup_enrichment.workflow"


class TestResolveWizardRescoreSignupInputs(BaseTest):
    def _resolve(self, organization_id: str) -> dict | None:
        return async_to_sync(resolve_wizard_rescore_signup_inputs_activity)(
            WizardStampRescoreInputs(organization_id=organization_id)
        )

    def test_resolves_identity_and_role_from_the_earliest_member(self):
        organization = Organization.objects.create(name="wizard.example")
        user = User.objects.create_user(email="founder@wizard.example", password=None, first_name="f")
        OrganizationMembership.objects.create(organization=organization, user=user)
        OrganizationEnrichment.objects.create(organization=organization, data={"signup_role": "engineering"})

        result = self._resolve(str(organization.id))

        assert result == {
            "organization_id": str(organization.id),
            "distinct_id": user.distinct_id,
            "domain": "wizard.example",
            "role_at_organization": "engineering",
        }

    def test_role_is_none_without_a_recorded_signup_role(self):
        organization = Organization.objects.create(name="norole.example")
        user = User.objects.create_user(email="founder@norole.example", password=None, first_name="f")
        OrganizationMembership.objects.create(organization=organization, user=user)

        result = self._resolve(str(organization.id))

        assert result is not None
        assert result["role_at_organization"] is None

    def test_returns_none_when_the_organization_has_no_member(self):
        organization = Organization.objects.create(name="ghost.example")

        assert self._resolve(str(organization.id)) is None

    def test_returns_none_for_a_generic_email_domain(self):
        organization = Organization.objects.create(name="personal.example")
        user = User.objects.create_user(email="someone@gmail.com", password=None, first_name="f")
        OrganizationMembership.objects.create(organization=organization, user=user)

        assert self._resolve(str(organization.id)) is None


_TASK_QUEUE = "wizard-stamp-rescore-test-queue"
_SIGNUP_INPUTS_DICT = {
    "organization_id": "org-1",
    "distinct_id": "d1",
    "domain": "stripe.com",
    "role_at_organization": "engineering",
}


async def _run_workflow(resolved_inputs, enrich_side_effect=None):
    @activity.defn(name=resolve_wizard_rescore_signup_inputs_activity.__name__)
    async def _fake_resolve(_inputs: WizardStampRescoreInputs) -> dict | None:
        return resolved_inputs

    enrich = AsyncMock(
        side_effect=enrich_side_effect
        or [
            EnrichmentOutcome(
                provider_fields=EnrichmentFields(company_type="STARTUP"), fit=IcpFitResult(status="scored", score=61)
            )
        ]
    )
    pha_client = MagicMock()
    with (
        patch(f"{_WORKFLOW_MODULE}.get_regional_ph_client", return_value=pha_client),
        patch(f"{_WORKFLOW_MODULE}.enrich_organization", enrich),
        patch(f"{_WORKFLOW_MODULE}._deterministic_company_type", return_value=None),
        patch("posthog.models.Organization.objects") as org_objects,
    ):
        org_objects.filter.return_value.exists.return_value = True
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[WizardStampRescoreWorkflow],
                activities=[_fake_resolve, enrich_signup_organization_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                result = await env.client.execute_workflow(
                    WizardStampRescoreWorkflow.run,
                    WizardStampRescoreInputs(organization_id="org-1"),
                    id=f"wizard-stamp-rescore-{uuid.uuid4()}",
                    task_queue=_TASK_QUEUE,
                )
    return result, enrich, pha_client


async def test_rescores_with_the_resolved_identity_after_the_settle_delay():
    result, enrich, _ = await _run_workflow(_SIGNUP_INPUTS_DICT)

    assert result == {"matched": True, "fields_filled": 1}
    enrich.assert_awaited_once()
    assert enrich.await_args.kwargs["is_recheck"] is True
    assert enrich.await_args.kwargs["role_at_organization"] == "engineering"
    assert enrich.await_args.kwargs["domain"] == "stripe.com"


async def test_skips_the_enrich_activity_when_no_signup_identity_resolves():
    result, enrich, _ = await _run_workflow(None)

    assert result == {"matched": False, "skipped": "no_signup_identity"}
    enrich.assert_not_awaited()


async def test_first_attempt_matched_is_pinned_true_so_upgraded_never_fires():
    outcome = EnrichmentOutcome(
        provider_fields=EnrichmentFields(company_type="STARTUP"), fit=IcpFitResult(status="scored", score=61)
    )
    _, _, pha_client = await _run_workflow(_SIGNUP_INPUTS_DICT, enrich_side_effect=[outcome])

    recheck_events = [c for c in pha_client.capture.call_args_list if c.kwargs["event"] == "signup_enrichment_recheck"]
    assert len(recheck_events) == 1
    assert recheck_events[0].kwargs["properties"]["upgraded"] is False


class TestDispatchWizardStampRescore:
    class _InlineExecutor:
        def submit(self, fn, *args):
            fn(*args)

    def setup_method(self):
        self._executor_patch = patch(f"{_TRIGGER_MODULE}._dispatch_executor", self._InlineExecutor())
        self._executor_patch.start()

    def teardown_method(self):
        self._executor_patch.stop()

    def _dispatch_mocks(self):
        return (
            patch(f"{_TRIGGER_MODULE}.sync_connect"),
            patch(f"{_TRIGGER_MODULE}.asyncio.run"),
        )

    @override_settings(SIGNUP_ENRICHMENT_TASK_QUEUE="signup-enrichment-test-queue")
    def test_starts_the_workflow_with_the_dedupe_id_and_task_queue(self):
        connect, run = self._dispatch_mocks()
        with connect as connect_mock, run:
            dispatch_wizard_stamp_rescore("org-1")

        connect_mock.assert_called_once()
        args, kwargs = connect_mock.return_value.start_workflow.call_args
        assert args[0] == "wizard-stamp-rescore"
        assert args[1] == WizardStampRescoreInputs(organization_id="org-1")
        assert kwargs["id"] == "wizard-stamp-rescore-org-1"
        assert kwargs["task_queue"] == "signup-enrichment-test-queue"

    def test_already_running_workflow_is_a_no_op_not_an_error(self):
        connect, run = self._dispatch_mocks()
        with connect, run as run_mock:
            run_mock.side_effect = WorkflowAlreadyStartedError("wizard-stamp-rescore-org-1", "wizard-stamp-rescore")
            with patch(f"{_TRIGGER_MODULE}.capture_exception") as capture_mock:
                dispatch_wizard_stamp_rescore("org-1")  # must not raise

        capture_mock.assert_not_called()

    def test_dispatch_dropped_when_backlog_full(self):
        import threading

        full = threading.BoundedSemaphore(1)
        full.acquire()
        connect, run = self._dispatch_mocks()
        with patch(f"{_TRIGGER_MODULE}._dispatch_slots", full):
            with connect as connect_mock, run:
                dispatch_wizard_stamp_rescore("org-1")
        connect_mock.assert_not_called()
