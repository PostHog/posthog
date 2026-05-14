"""Temporal activities for the hourly referral research flows.

Each activity:
1. Resolves a sandbox context for the local team/user (same path the management commands use).
2. Runs the research agent (Twitter or internal).
3. Calls a placeholder side-effect hook so the downstream wire-up (reply tweets / send emails)
   is easy to find when it is implemented.

The output is logged at INFO; the structured return value also surfaces in the Temporal UI's
workflow result so an operator can read it without grepping logs.
"""

from __future__ import annotations

import os
import time
import logging
import dataclasses
from dataclasses import dataclass

import temporalio.activity

from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal

from products.referrals.backend.internal.research.prompts import InternalReferralCandidates
from products.referrals.backend.internal.research.research import run_internal_research
from products.referrals.backend.temporal.constants import TWITTER_DEFAULT_HOURS
from products.referrals.backend.twitter.research.prompts import TwitterReferralCandidates
from products.referrals.backend.twitter.research.research import run_twitter_research
from products.tasks.backend.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev

logger = logging.getLogger(__name__)

# Small dummy repo: neither agent needs the PostHog source tree, but Task.create_and_run still
# requires a GitHub integration to bootstrap the sandbox clone.
_DEFAULT_REPOSITORY = "PostHog/.github"


@dataclass
class TwitterReferralResearchActivityInput:
    hours: int = TWITTER_DEFAULT_HOURS
    repository: str = _DEFAULT_REPOSITORY


@dataclass
class InternalReferralResearchActivityInput:
    repository: str = _DEFAULT_REPOSITORY


def _post_referral_replies_placeholder(result: TwitterReferralCandidates) -> None:
    """Placeholder: will post a referral-ask reply tweet to each candidate's original tweet.

    TODO(referrals): wire this up to the twitterapi.io reply endpoint once we have approval
    to post on the PostHog handle. Until then, log what we WOULD reply to so the schedule's
    output is observable.
    """
    logger.warning(
        "twitter referral reply hook not implemented — %d candidate(s) would receive a reply",
        len(result.candidates),
    )
    for candidate in result.candidates:
        logger.info(
            "twitter referral reply (placeholder): tweet_id=%s user=@%s reason=%s",
            candidate.id,
            candidate.user,
            candidate.reason,
        )


def _send_referral_emails_placeholder(result: InternalReferralCandidates) -> None:
    """Placeholder: will send a personal referral-ask email to each internal candidate.

    TODO(referrals): wire this up to the messaging product (or a direct SES send) once we
    have copy + approval. Until then, log what we WOULD email so the schedule's output is
    observable.
    """
    logger.warning(
        "internal referral email hook not implemented — %d candidate(s) would receive an email",
        len(result.candidates),
    )
    for candidate in result.candidates:
        logger.info(
            "internal referral email (placeholder): distinct_id=%s email=%s org=%s reason=%s",
            candidate.distinct_id,
            candidate.email,
            candidate.org_name,
            candidate.reason,
        )


@temporalio.activity.defn
@scoped_temporal()
async def run_twitter_referral_research_activity(
    input: TwitterReferralResearchActivityInput,
) -> int:
    """Run the Twitter referral research agent for the last `hours` hours.

    Returns the number of candidates found. Side effects (the reply tweets) are dispatched
    via `_post_referral_replies_placeholder` inside the activity, so they are retried with
    the activity if the workflow restarts mid-run.
    """
    api_key = os.environ.get("TWITTERAPI_IO_KEY")
    if not api_key:
        # ValueError is in `non_retryable_error_types` — config errors should fail loud, not loop.
        raise ValueError("TWITTERAPI_IO_KEY is not set in the worker environment")

    since_unix_ts = int(time.time()) - input.hours * 3600

    async with Heartbeater():
        context = resolve_sandbox_context_for_local_dev(input.repository)
        logger.info(
            "twitter_referral_research_activity: starting team=%d user=%d hours=%d since_unix_ts=%d",
            context.team_id,
            context.user_id,
            input.hours,
            since_unix_ts,
        )
        result = await run_twitter_research(
            context,
            api_key=api_key,
            since_unix_ts=since_unix_ts,
            hours=input.hours,
        )
        logger.info(
            "twitter_referral_research_activity: agent returned %d candidate(s)",
            len(result.candidates),
        )
        _post_referral_replies_placeholder(result)
    return len(result.candidates)


@temporalio.activity.defn
@scoped_temporal()
async def run_internal_referral_research_activity(
    input: InternalReferralResearchActivityInput,
) -> int:
    """Run the internal-user referral research agent over PostHog's own behavioural data.

    `posthog_mcp_scopes` must be layered on for the agent to call MCP's `execute-sql` — the
    local-dev resolver leaves it unset by default so production callers stay explicit about
    what scopes they grant.
    """
    async with Heartbeater():
        base_context = resolve_sandbox_context_for_local_dev(input.repository)
        context = dataclasses.replace(base_context, posthog_mcp_scopes="read_only")
        logger.info(
            "internal_referral_research_activity: starting team=%d user=%d",
            context.team_id,
            context.user_id,
        )
        result = await run_internal_research(context)
        logger.info(
            "internal_referral_research_activity: agent returned %d candidate(s)",
            len(result.candidates),
        )
        _send_referral_emails_placeholder(result)
    return len(result.candidates)
