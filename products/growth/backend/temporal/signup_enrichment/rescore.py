"""Event-driven ICP re-score triggered when the setup wizard's AI-SDK stamp lands on an org's group properties.

Delegates to enrich_signup_organization_activity so scoring stays identical to the +4h recheck.
"""

import json
import typing
import datetime as dt
import dataclasses

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.growth.backend.temporal.signup_enrichment.workflow import (
    ENRICH_ACTIVITY_TIMEOUT,
    MAX_ENRICH_ATTEMPTS,
    SignupEnrichmentInputs,
    enrich_signup_organization_activity,
)

LOGGER = get_logger(__name__)

RESOLVE_ACTIVITY_TIMEOUT = dt.timedelta(seconds=30)

# Lets the stamp's group-property write land before the recheck reads it.
STAMP_SETTLE_DELAY = dt.timedelta(seconds=60)


@dataclasses.dataclass(frozen=True)
class WizardStampRescoreInputs:
    organization_id: str


@activity.defn
@close_db_connections
async def resolve_wizard_rescore_signup_inputs_activity(
    inputs: WizardStampRescoreInputs,
) -> typing.Optional[dict[str, typing.Any]]:
    """Reads the org's earliest membership to fill in the signup identity, since the webhook body carries only the organization id."""
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    from posthog.models.organization import OrganizationMembership  # noqa: PLC0415
    from posthog.utils import GenericEmails  # noqa: PLC0415

    from products.growth.backend.models import OrganizationEnrichment  # noqa: PLC0415
    from products.growth.backend.temporal.signup_enrichment.trigger import domain_from_email  # noqa: PLC0415

    logger = LOGGER.bind(organization_id=inputs.organization_id)

    def _resolve() -> typing.Optional[dict[str, typing.Any]]:
        membership = (
            OrganizationMembership.objects.filter(organization_id=inputs.organization_id)
            .select_related("user")
            .order_by("joined_at")
            .first()
        )
        if membership is None or membership.user is None:
            return None
        user = membership.user
        domain = domain_from_email(user.email) if user.email else None
        if not user.distinct_id or not domain or GenericEmails().is_generic(user.email):
            return None

        record = OrganizationEnrichment.objects.filter(organization_id=inputs.organization_id).only("data").first()
        role = record.data.get("signup_role") if record else None

        return {
            "organization_id": inputs.organization_id,
            "distinct_id": user.distinct_id,
            "domain": domain,
            "role_at_organization": role,
        }

    resolved = await sync_to_async(_resolve)()
    if resolved is None:
        logger.info("wizard_stamp_rescore_no_signup_identity")
    return resolved


@workflow.defn(name="wizard-stamp-rescore")
class WizardStampRescoreWorkflow(PostHogWorkflow):
    """Runs independently of SignupEnrichmentWorkflow's own +4h recheck: an org can get both, or only whichever fires first, since either one lands the same wizard-aware score."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> WizardStampRescoreInputs:
        return WizardStampRescoreInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: WizardStampRescoreInputs) -> dict[str, typing.Any]:
        await workflow.sleep(STAMP_SETTLE_DELAY)

        signup_inputs = await workflow.execute_activity(
            resolve_wizard_rescore_signup_inputs_activity,
            inputs,
            start_to_close_timeout=RESOLVE_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if signup_inputs is None:
            return {"matched": False, "skipped": "no_signup_identity"}

        # first_attempt_matched is pinned True because this trigger has no first attempt to compare against, keeping the recheck-only "upgraded" property from firing here.
        return await workflow.execute_activity(
            enrich_signup_organization_activity,
            args=[SignupEnrichmentInputs(**signup_inputs), True, True],
            start_to_close_timeout=ENRICH_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=MAX_ENRICH_ATTEMPTS, initial_interval=dt.timedelta(seconds=5)),
        )
