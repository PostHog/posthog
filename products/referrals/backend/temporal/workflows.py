"""Temporal workflows that wrap each referral research activity for hourly scheduling.

The workflows themselves are thin: schedule fires the workflow once an hour, the workflow
executes its activity, the activity orchestrates the sandbox session. Splitting them this
way keeps the schedule/workflow surface independent of the sandbox lifecycle and lets us
swap the activity logic without touching the scheduler.
"""

from __future__ import annotations

import json

import temporalio.workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.referrals.backend.temporal.activities import (
    InternalReferralResearchActivityInput,
    TwitterReferralResearchActivityInput,
    run_internal_referral_research_activity,
    run_twitter_referral_research_activity,
)
from products.referrals.backend.temporal.constants import (
    INTERNAL_RESEARCH_WORKFLOW_NAME,
    RESEARCH_ACTIVITY_TIMEOUT,
    RESEARCH_HEARTBEAT_TIMEOUT,
    RESEARCH_RETRY_POLICY,
    TWITTER_RESEARCH_WORKFLOW_NAME,
)


@temporalio.workflow.defn(name=TWITTER_RESEARCH_WORKFLOW_NAME)
class TwitterReferralResearchWorkflow(PostHogWorkflow):
    """Hourly: scan the last hour of PostHog tweets and (eventually) reply to good candidates."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> TwitterReferralResearchActivityInput:
        if not inputs:
            return TwitterReferralResearchActivityInput()
        loaded = json.loads(inputs[0])
        return TwitterReferralResearchActivityInput(**loaded)

    @temporalio.workflow.run
    async def run(self, input: TwitterReferralResearchActivityInput) -> int:
        return await temporalio.workflow.execute_activity(
            run_twitter_referral_research_activity,
            input,
            start_to_close_timeout=RESEARCH_ACTIVITY_TIMEOUT,
            heartbeat_timeout=RESEARCH_HEARTBEAT_TIMEOUT,
            retry_policy=RESEARCH_RETRY_POLICY,
        )


@temporalio.workflow.defn(name=INTERNAL_RESEARCH_WORKFLOW_NAME)
class InternalReferralResearchWorkflow(PostHogWorkflow):
    """Hourly: surface PostHog power users who look like referral targets and (eventually) email them."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> InternalReferralResearchActivityInput:
        if not inputs:
            return InternalReferralResearchActivityInput()
        loaded = json.loads(inputs[0])
        return InternalReferralResearchActivityInput(**loaded)

    @temporalio.workflow.run
    async def run(self, input: InternalReferralResearchActivityInput) -> int:
        return await temporalio.workflow.execute_activity(
            run_internal_referral_research_activity,
            input,
            start_to_close_timeout=RESEARCH_ACTIVITY_TIMEOUT,
            heartbeat_timeout=RESEARCH_HEARTBEAT_TIMEOUT,
            retry_policy=RESEARCH_RETRY_POLICY,
        )
