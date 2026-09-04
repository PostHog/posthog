"""Event-driven ICP re-score: a PostHog realtime destination calls the webhook in
products/growth/backend/api/rescore.py the moment the setup wizard's AI-SDK stamp lands on an
org's group properties, so the score doesn't wait on the standing +4h recheck
(products/growth/backend/temporal/signup_enrichment/workflow.py) or the daily sweep
(reenrichment.py) to catch it. Dispatch lives in trigger.py, alongside the signup dispatch it
shares a pool with.

Delegates straight to enrich_signup_organization_activity: the same activity the +4h recheck
runs: so archiving, scoring, and the person mirror never diverge between the two triggers.
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

# The webhook fires the instant the stamp's group_identify lands; a short pause keeps the
# resolve activity from reading the org's bridge inputs before that write is visible.
STAMP_SETTLE_DELAY = dt.timedelta(seconds=60)


@dataclasses.dataclass(frozen=True)
class WizardStampRescoreInputs:
    organization_id: str


@activity.defn
@close_db_connections
async def resolve_wizard_rescore_signup_inputs_activity(
    inputs: WizardStampRescoreInputs,
) -> typing.Optional[dict[str, typing.Any]]:
    """The signup identity enrich_signup_organization_activity needs, read from the org's
    membership: the webhook's body carries only the organization id.

    Returns None when no member can stand in for the signup identity (org deleted, no
    distinct_id, no resolvable work-email domain), which the workflow treats as nothing to do.
    """
    from asgiref.sync import sync_to_async  # noqa: PLC0415: heavy import kept off the workflow module path

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
    """Re-score one org's ICP fit once its wizard AI-SDK stamp lands.

    Runs independently of SignupEnrichmentWorkflow's own +4h recheck: an org can get both, or
    only whichever fires first, since either one lands the same wizard-aware score.
    """

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

        # first_attempt_matched=True: this trigger has no first attempt of its own to compare
        # against, so it is pinned to keep the recheck event's "upgraded" property: which
        # reports on the +4h recheck's own Harmonic-timing story: from firing here instead.
        return await workflow.execute_activity(
            enrich_signup_organization_activity,
            args=[SignupEnrichmentInputs(**signup_inputs), True, True],
            start_to_close_timeout=ENRICH_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=MAX_ENRICH_ATTEMPTS, initial_interval=dt.timedelta(seconds=5)),
        )
