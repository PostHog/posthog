"""Nightly-ish orchestrator for referee status checks (starts with ingestion stage)."""

from __future__ import annotations

import json
import asyncio
from datetime import timedelta

from temporalio import common, workflow

from posthog.temporal.common.base import PostHogWorkflow

from products.referrals.backend.temporal.activities import (
    referral_status_issue_shopify_codes_activity,
    referral_status_list_pending_ingestion_activity,
    referral_status_process_single_ingestion_activity,
    referral_status_record_ingestion_check_failure_activity,
    referral_status_send_shopify_reward_emails_activity,
)
from products.referrals.backend.temporal.types import (
    IssueShopifyCodesInput,
    ProcessSingleReferralIngestionInput,
    RecordIngestionCheckFailureInput,
    SendShopifyRewardEmailsInput,
    SocialReferralStatusInputs,
)

LIST_RETRY = common.RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10), backoff_coefficient=2.0)

PER_REFERRAL_RETRY = common.RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
)

FAILURE_RECORD_RETRY = common.RetryPolicy(
    maximum_attempts=5,
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
)

# Match prior single-activity run budget; each row is cheap.
_LIST_TIMEOUT = timedelta(minutes=30)
_PER_REFERRAL_TIMEOUT = timedelta(minutes=10)
_FAILURE_RECORD_TIMEOUT = timedelta(minutes=2)
_SEND_REWARD_EMAIL_TIMEOUT = timedelta(minutes=2)


@workflow.defn(name="social-referral-status")
class SocialReferralStatusWorkflow(PostHogWorkflow):
    """Chains referral maintenance activities; ingestion stage discovers first captured events."""

    @classmethod
    def parse_inputs(cls, inputs: list[str]) -> SocialReferralStatusInputs:
        if not inputs:
            return SocialReferralStatusInputs()
        loaded = json.loads(inputs[0])
        return SocialReferralStatusInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SocialReferralStatusInputs) -> dict[str, int]:
        snapshot = await workflow.execute_activity(
            referral_status_list_pending_ingestion_activity,
            start_to_close_timeout=_LIST_TIMEOUT,
            retry_policy=LIST_RETRY,
        )

        referral_ids: list[str] = snapshot["referral_ids"]
        base: dict[str, int] = {
            "pending_referee_org_count": snapshot["pending_referee_org_count"],
            "org_keys_evaluated_valid": snapshot["org_keys_evaluated_valid"],
            "org_skipped_invalid_uuid": snapshot["org_skipped_invalid_uuid"],
            "referee_orgs_without_teams": snapshot["referee_orgs_without_teams"],
        }

        if not referral_ids:
            return {
                **base,
                "referees_rows_updated": 0,
                "referrals_checked": 0,
                "referrals_failed": 0,
            }

        sem = asyncio.Semaphore(inputs.max_concurrent_referral_checks)

        async def _run_one(referral_row_id: str) -> dict[str, int]:
            async with sem:
                flip_result = await workflow.execute_activity(
                    referral_status_process_single_ingestion_activity,
                    ProcessSingleReferralIngestionInput(social_referral_id=referral_row_id),
                    start_to_close_timeout=_PER_REFERRAL_TIMEOUT,
                    retry_policy=PER_REFERRAL_RETRY,
                )
                orgs_flipped = int(flip_result["orgs_flipped"])
                flipped_keys: list[str] = list(flip_result.get("flipped_org_keys") or [])
                if flipped_keys:
                    rewards = await workflow.execute_activity(
                        referral_status_issue_shopify_codes_activity,
                        IssueShopifyCodesInput(social_referral_id=referral_row_id, flipped_org_keys=flipped_keys),
                        start_to_close_timeout=_PER_REFERRAL_TIMEOUT,
                        retry_policy=PER_REFERRAL_RETRY,
                    )
                    if rewards:
                        await workflow.execute_activity(
                            referral_status_send_shopify_reward_emails_activity,
                            SendShopifyRewardEmailsInput(rewards=list(rewards)),
                            start_to_close_timeout=_SEND_REWARD_EMAIL_TIMEOUT,
                            retry_policy=FAILURE_RECORD_RETRY,
                        )
                return {"orgs_flipped": orgs_flipped}

        results = await asyncio.gather(*(_run_one(rid) for rid in referral_ids), return_exceptions=True)

        total_flipped = 0
        failed = 0
        for referral_row_id, res in zip(referral_ids, results, strict=True):
            if isinstance(res, BaseException):
                failed += 1
                workflow.logger.warning(
                    f"social_referral_status: single-referral ingestion activity failed ({referral_row_id}): {res!r}"
                )
                try:
                    await workflow.execute_activity(
                        referral_status_record_ingestion_check_failure_activity,
                        RecordIngestionCheckFailureInput(
                            social_referral_id=referral_row_id,
                            error_detail=repr(res),
                        ),
                        start_to_close_timeout=_FAILURE_RECORD_TIMEOUT,
                        retry_policy=FAILURE_RECORD_RETRY,
                    )
                except Exception as persist_exc:
                    workflow.logger.warning(
                        f"social_referral_status: could not persist ingestion failure on row ({referral_row_id}): {persist_exc!r}"
                    )
            else:
                total_flipped += res["orgs_flipped"]

        return {
            **base,
            "referees_rows_updated": total_flipped,
            "referrals_checked": len(referral_ids),
            "referrals_failed": failed,
        }
