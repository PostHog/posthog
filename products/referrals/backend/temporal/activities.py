"""Temporal activities for the referrals product.

Two unrelated concerns share this module:

1. **Research flows** (hourly) — surface Twitter and internal referral candidates via the
   sandbox-based research agents. Each activity resolves a sandbox context, runs the
   agent, and dispatches the side effect inline: the Twitter flow DMs each candidate; the
   internal flow's email hook is still a placeholder.
2. **Social referral referee status sync** (nightly) — scan ``SocialReferral.referee_state``
   for orgs that have started sending events, flip the per-org ``first_event_sent`` flag,
   issue optional Shopify referrer codes when configured, and always send a **merch reward**
   email per flipped org with a referring user (in-process SMTP; copy does not include a code). Temporal
   uses three activities per row (flip, issue Shopify codes, send notices).

The two concerns are kept side-by-side rather than split into two modules because they
ship under the same product and the registration boilerplate already lives in one
``__init__.py``. They share no helpers.
"""

from __future__ import annotations

import os
import time
import logging
import dataclasses
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
import temporalio.activity
from temporalio import activity

from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async
from posthog.tasks.email import deliver_social_referral_merch_reward_notice_email
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal

from products.referrals.backend.internal.research.prompts import InternalReferralCandidates
from products.referrals.backend.internal.research.research import run_internal_research
from products.referrals.backend.models import (
    REFEREE_ENTRY_SHOPIFY_CODE_RECORD_CODE,
    REFEREE_ENTRY_SHOPIFY_CODE_RECORD_DISCOUNT_ID,
    REFEREE_ENTRY_SHOPIFY_CODE_RECORD_ISSUED_AT,
    REFEREE_ENTRY_SHOPIFY_CODE_RECORD_PRICE_RULE_ID,
    REFEREE_ENTRY_SHOPIFY_DISCOUNT_CODES_KEY,
    REFEREE_ENTRY_SHOPIFY_PROMO_LAST_ERROR_KEY,
    REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY,
    REFEREE_STATE_ERRORS_KEY,
    SocialReferral,
)
from products.referrals.backend.shopify_referrer_promo import (
    REFERRALS_SHOPIFY_PRICE_RULE_ID,
    create_referrer_discount_code,
    social_referral_shopify_promo_configured,
)
from products.referrals.backend.temporal.constants import TWITTER_DEFAULT_HOURS
from products.referrals.backend.temporal.types import (
    IssueShopifyCodesInput,
    ProcessSingleReferralIngestionInput,
    RecordIngestionCheckFailureInput,
    SendReferralIngestionNoticeEmailsInput,
    ShopifyRewardEmailItem,
)
from products.referrals.backend.twitter.research.prompts import TwitterReferralCandidates
from products.referrals.backend.twitter.research.research import run_twitter_research
from products.referrals.backend.twitter.x_dm import send_referral_dms
from products.tasks.backend.services.dev_sandbox_context import resolve_sandbox_context_for_local_dev

logger = logging.getLogger(__name__)
_LOGGER = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Research flows (Twitter + internal-users)
# ---------------------------------------------------------------------------

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


_TWITTER_DM_TEMPLATE = "Hey, {nickname}, Posthog Referrals is coming soon"


async def _post_referral_dms(result: TwitterReferralCandidates) -> None:
    """DM each candidate via the X v2 API.

    TODO(referrals): make this idempotent before promoting beyond the hackathon — currently
    nothing prevents re-DMing the same handle if a tweet re-surfaces in a later window. Pick
    a key (tweet_id or twitter_user_id), persist in a small model, and skip-on-conflict.
    """
    if not result.candidates:
        logger.info("twitter referral dm: no candidates this run")
        return
    handle_to_text = [
        (candidate.user, _TWITTER_DM_TEMPLATE.format(nickname=candidate.user)) for candidate in result.candidates
    ]
    for candidate in result.candidates:
        logger.info(
            "twitter referral dm (queued): tweet_id=%s user=@%s reason=%s",
            candidate.id,
            candidate.user,
            candidate.reason,
        )
    summary = await send_referral_dms(handle_to_text)
    logger.info(
        "twitter referral dm summary: sent=%d failed_lookup=%d failed_send=%d",
        summary.sent,
        summary.failed_lookup,
        summary.failed_send,
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

    Returns the number of candidates found. Side effects (the DMs) are dispatched via
    `_post_referral_dms` inside the activity, so they are retried with the activity if the
    workflow restarts mid-run.
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
        # TEMP(referrals): hackathon override — DM only @nightowl_coder once per run instead of
        # iterating over every candidate the agent found. The list-of-one means there's no
        # loop to break out of; the original behavior is `await _post_referral_dms(result)`.
        test_handle = "nightowl_coder"
        test_text = (
            "you didn't ask for this DM. we didn't ask to be loved on twitter. here we are. posthog.com/pyramide"
        )
        # TODO: Disabled temporary to avoid spamming. Uncomment to re-enable.
        # summary = await send_referral_dms([(test_handle, test_text)])
        # logger.info(
        #     "twitter referral dm summary (single-recipient override): sent=%d failed_lookup=%d failed_send=%d",
        #     summary.sent, summary.failed_lookup, summary.failed_send,
        # )
        logger.info("twitter referral dm SKIPPED (would have sent to=@%s text=%r)", test_handle, test_text)
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
        for candidate in result.candidates:
            logger.info(
                "internal referral email (queued): distinct_id=%s email=%s org=%s reason=%s",
                candidate.distinct_id,
                candidate.email,
                candidate.org_name,
                candidate.reason,
            )
        # TEMP(referrals): hackathon override — email only test@posthog.com once per run
        # instead of iterating over every candidate the agent found. Original behavior is
        # `_send_referral_emails_placeholder(result)`; promote to a per-candidate loop with
        # idempotency before sending for real.
        test_recipient = "test@posthog.com"
        # TODO: Disabled temporary to avoid spamming. Uncomment to re-enable.
        # send_internal_referral_invite_email.apply(
        #     kwargs={"recipient_email": test_recipient, "enqueue_email_delivery": False},
        #     throw=True,
        # )
        logger.info("internal referral email sent (single-recipient override): to=%s", test_recipient)
    return len(result.candidates)


# ---------------------------------------------------------------------------
# Social referral referee status sync (nightly ingestion stage)
# ---------------------------------------------------------------------------

FIRST_EVENT_SENT_KEY = "first_event_sent"
INGESTION_CHECK_FAILURE_DETAIL_MAX_LEN = 4000

_LEGACY_SHOPIFY_SCALAR_KEYS = ("shopify_discount_code", "shopify_promo_issued_at", "shopify_price_rule_id")
_SHOPIFY_PROMO_ERROR_MAX_LEN = 2000


def referee_entry_pending_first_event(entry: object) -> bool:
    """True unless `first_event_sent` is explicitly true."""
    if not isinstance(entry, dict):
        return True
    return entry.get(FIRST_EVENT_SENT_KEY) is not True


def _is_reserved_referee_state_key(org_key: str) -> bool:
    return org_key == REFEREE_STATE_ERRORS_KEY


def _normalized_discount_code_list(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = item.get(REFEREE_ENTRY_SHOPIFY_CODE_RECORD_CODE)
        if not isinstance(code, str) or not code:
            continue
        issued = item.get(REFEREE_ENTRY_SHOPIFY_CODE_RECORD_ISSUED_AT)
        rule = item.get(REFEREE_ENTRY_SHOPIFY_CODE_RECORD_PRICE_RULE_ID)
        disc_id_raw = item.get(REFEREE_ENTRY_SHOPIFY_CODE_RECORD_DISCOUNT_ID)
        rec: dict[str, Any] = {REFEREE_ENTRY_SHOPIFY_CODE_RECORD_CODE: code}
        if isinstance(issued, str) and issued:
            rec[REFEREE_ENTRY_SHOPIFY_CODE_RECORD_ISSUED_AT] = issued
        if isinstance(rule, str) and rule:
            rec[REFEREE_ENTRY_SHOPIFY_CODE_RECORD_PRICE_RULE_ID] = rule
        if disc_id_raw is not None and disc_id_raw != "":
            rec[REFEREE_ENTRY_SHOPIFY_CODE_RECORD_DISCOUNT_ID] = str(disc_id_raw)
        out.append(rec)
    return out


def _attach_shopify_promo_to_referee_entry(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    """Mutate referee entry after `first_event_sent` flip: append a Shopify code when configured.

    Returns ``(discount_code, shopify_discount_id)`` when creation succeeds; ``(None, None)`` otherwise.
    """
    promo = create_referrer_discount_code()
    if promo.code is not None:
        codes = _normalized_discount_code_list(entry.get(REFEREE_ENTRY_SHOPIFY_DISCOUNT_CODES_KEY))
        record: dict[str, Any] = {
            REFEREE_ENTRY_SHOPIFY_CODE_RECORD_CODE: promo.code,
            REFEREE_ENTRY_SHOPIFY_CODE_RECORD_ISSUED_AT: timezone.now().isoformat(),
            REFEREE_ENTRY_SHOPIFY_CODE_RECORD_PRICE_RULE_ID: REFERRALS_SHOPIFY_PRICE_RULE_ID,
        }
        if promo.shopify_discount_id:
            record[REFEREE_ENTRY_SHOPIFY_CODE_RECORD_DISCOUNT_ID] = promo.shopify_discount_id
        codes.append(record)
        entry[REFEREE_ENTRY_SHOPIFY_DISCOUNT_CODES_KEY] = codes
        entry.pop(REFEREE_ENTRY_SHOPIFY_PROMO_LAST_ERROR_KEY, None)
        for legacy in _LEGACY_SHOPIFY_SCALAR_KEYS:
            entry.pop(legacy, None)
        return promo.code, promo.shopify_discount_id
    if promo.error_detail is not None:
        entry[REFEREE_ENTRY_SHOPIFY_PROMO_LAST_ERROR_KEY] = promo.error_detail[:_SHOPIFY_PROMO_ERROR_MAX_LEN]
    return None, None


def _clear_ingestion_sync_error_from_merged(merged: dict[str, Any]) -> bool:
    """Remove ``errors.ingestion_sync``; drop ``errors`` if empty. Returns whether ``merged`` changed."""
    errors_raw = merged.get(REFEREE_STATE_ERRORS_KEY)
    if not isinstance(errors_raw, dict) or REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY not in errors_raw:
        return False
    err = dict(errors_raw)
    del err[REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY]
    if err:
        merged[REFEREE_STATE_ERRORS_KEY] = err
    else:
        merged.pop(REFEREE_STATE_ERRORS_KEY, None)
    return True


def record_ingestion_check_failure_on_referral_sync(referral_id: UUID, error_detail: str) -> bool:
    """Write last ingestion activity failure under ``referee_state.errors.ingestion_sync``."""
    detail = error_detail[:INGESTION_CHECK_FAILURE_DETAIL_MAX_LEN]
    with transaction.atomic():
        referral = SocialReferral.objects.select_for_update().filter(id=referral_id).first()
        if referral is None:
            return False
        merged = dict(referral.referee_state) if isinstance(referral.referee_state, dict) else {}
        errors: dict[str, Any] = {}
        existing_errors = merged.get(REFEREE_STATE_ERRORS_KEY)
        if isinstance(existing_errors, dict):
            errors = dict(existing_errors)
        errors[REFEREE_STATE_ERRORS_INGESTION_SYNC_KEY] = {
            "last_failure_at": timezone.now().isoformat(),
            "last_failure_detail": detail,
        }
        merged[REFEREE_STATE_ERRORS_KEY] = errors
        referral.referee_state = merged
        referral.save(update_fields=["referee_state"])
    return True


def _compute_org_level_diagnostics(referee_org_to_row_ids: dict[str, list[UUID]]) -> dict[str, int]:
    org_keys_evaluated_valid = 0
    org_skipped_invalid_uuid = 0
    referee_orgs_without_teams = 0
    for org_uuid_str in referee_org_to_row_ids:
        try:
            org_uuid = UUID(org_uuid_str)
        except ValueError:
            org_skipped_invalid_uuid += 1
            _LOGGER.warning(
                "social_referral_status_invalid_org_uuid_referee_state",
                org_key_prefix=org_uuid_str[:64],
            )
            continue
        org_keys_evaluated_valid += 1
        if not Team.objects.filter(organization_id=org_uuid).exists():
            referee_orgs_without_teams += 1
    return {
        "org_keys_evaluated_valid": org_keys_evaluated_valid,
        "org_skipped_invalid_uuid": org_skipped_invalid_uuid,
        "referee_orgs_without_teams": referee_orgs_without_teams,
    }


def build_pending_ingestion_snapshot() -> dict[str, Any]:
    """Build org index, org-level pre-checks, and referral ids that still have pending entries."""
    referee_org_to_row_ids: dict[str, list[UUID]] = {}
    referral_ids_with_any_pending: set[UUID] = set()

    qs = SocialReferral.objects.only("id", "referee_state").iterator(chunk_size=500)

    for row in qs:
        state = row.referee_state if isinstance(row.referee_state, dict) else {}
        row_id = row.id
        row_has_pending = False
        for org_key, payload in state.items():
            if not isinstance(org_key, str):
                continue
            if _is_reserved_referee_state_key(org_key):
                continue
            if not referee_entry_pending_first_event(payload):
                continue
            row_has_pending = True
            referee_org_to_row_ids.setdefault(org_key, []).append(row_id)
        if row_has_pending:
            referral_ids_with_any_pending.add(row_id)

    org_diag = _compute_org_level_diagnostics(referee_org_to_row_ids)

    referral_ids = sorted(str(rid) for rid in referral_ids_with_any_pending)

    return {
        "referral_ids": referral_ids,
        "pending_referee_org_count": len(referee_org_to_row_ids),
        **org_diag,
    }


def _flip_ingestion_for_referral(referral_id: UUID) -> dict[str, Any]:
    """Set ``first_event_sent`` for referee orgs that qualify; no Shopify or email."""
    orgs_flipped = 0
    flipped_org_keys: list[str] = []
    with transaction.atomic():
        referral = SocialReferral.objects.select_for_update().filter(id=referral_id).first()
        if referral is None:
            return {"orgs_flipped": 0, "flipped_org_keys": []}

        merged = dict(referral.referee_state) if isinstance(referral.referee_state, dict) else {}
        changed = False

        if _clear_ingestion_sync_error_from_merged(merged):
            changed = True

        for org_key, payload in list(merged.items()):
            if not isinstance(org_key, str):
                continue
            if _is_reserved_referee_state_key(org_key):
                continue
            if not referee_entry_pending_first_event(payload):
                continue
            try:
                org_uuid = UUID(org_key)
            except ValueError:
                continue
            if not Team.objects.filter(organization_id=org_uuid).exists():
                continue
            if not Team.objects.filter(organization_id=org_uuid, ingested_event=True).exists():
                continue

            entry_raw = merged.get(org_key)
            if isinstance(entry_raw, dict) and entry_raw.get(FIRST_EVENT_SENT_KEY) is True:
                continue
            if isinstance(entry_raw, dict):
                new_entry: dict[str, Any] = {**entry_raw, FIRST_EVENT_SENT_KEY: True}
            else:
                new_entry = {FIRST_EVENT_SENT_KEY: True}
            merged[org_key] = new_entry
            orgs_flipped += 1
            flipped_org_keys.append(org_key)
            changed = True

        if changed:
            referral.referee_state = merged
            referral.save(update_fields=["referee_state"])

    return {"orgs_flipped": orgs_flipped, "flipped_org_keys": flipped_org_keys}


def _issue_shopify_codes_for_referral_orgs(referral_id: UUID, org_keys: list[str]) -> list[ShopifyRewardEmailItem]:
    """Create Shopify codes for flipped org keys (idempotent if codes already present)."""
    if not org_keys or not social_referral_shopify_promo_configured():
        return []

    rewards: list[ShopifyRewardEmailItem] = []
    with transaction.atomic():
        referral = SocialReferral.objects.select_for_update().filter(id=referral_id).first()
        if referral is None:
            return []

        merged = dict(referral.referee_state) if isinstance(referral.referee_state, dict) else {}
        changed = False
        referer_user_id = referral.user_id

        for org_key in org_keys:
            entry_raw = merged.get(org_key)
            if not isinstance(entry_raw, dict):
                continue
            if entry_raw.get(FIRST_EVENT_SENT_KEY) is not True:
                continue

            new_code, shopify_discount_id = _attach_shopify_promo_to_referee_entry(entry_raw)
            merged[org_key] = entry_raw
            changed = True

            if new_code is not None and referer_user_id is not None:
                org_uuid = UUID(org_key)
                referee_name = Organization.objects.filter(id=org_uuid).values_list("name", flat=True).first() or ""
                rewards.append(
                    ShopifyRewardEmailItem(
                        user_id=referer_user_id,
                        discount_code=new_code,
                        shopify_discount_id=shopify_discount_id,
                        referee_organization_name=str(referee_name),
                    )
                )

        if changed:
            referral.referee_state = merged
            referral.save(update_fields=["referee_state"])

    return rewards


def _deliver_referral_shopify_reward_emails(referral_id: UUID, flipped_org_keys: list[str]) -> None:
    if not flipped_org_keys:
        return
    referral = SocialReferral.objects.filter(id=referral_id).first()
    if referral is None or referral.user_id is None:
        return
    uid = referral.user_id
    rid_str = str(referral_id)
    for org_key in flipped_org_keys:
        try:
            org_uuid = UUID(org_key)
        except ValueError:
            continue
        referee_name = Organization.objects.filter(id=org_uuid).values_list("name", flat=True).first() or org_key
        deliver_social_referral_merch_reward_notice_email(
            user_id=uid,
            referee_organization_name=str(referee_name),
            social_referral_id=rid_str,
            referee_organization_key=org_key,
        )


def process_single_social_referral_ingestion_sync(referral_id: UUID) -> dict[str, int]:
    flip = _flip_ingestion_for_referral(referral_id)
    flipped_keys = list(flip["flipped_org_keys"])
    try:
        _issue_shopify_codes_for_referral_orgs(referral_id, flipped_keys)
    except Exception:
        _LOGGER.exception("social_referral_shopify_issue_unexpected_failure", referral_id=str(referral_id))
    _deliver_referral_shopify_reward_emails(referral_id, flipped_keys)
    return {"orgs_flipped": flip["orgs_flipped"]}


def execute_referral_ingestion_stage_sweep() -> dict[str, int]:
    """Full scan (single process) — used by tests and emergency/manual runs."""
    snapshot = build_pending_ingestion_snapshot()
    total_orgs_flipped = 0
    for rid_str in snapshot["referral_ids"]:
        total_orgs_flipped += process_single_social_referral_ingestion_sync(UUID(rid_str))["orgs_flipped"]

    summary: dict[str, int] = {
        "pending_referee_org_count": snapshot["pending_referee_org_count"],
        "org_keys_evaluated_valid": snapshot["org_keys_evaluated_valid"],
        "org_skipped_invalid_uuid": snapshot["org_skipped_invalid_uuid"],
        "referee_orgs_without_teams": snapshot["referee_orgs_without_teams"],
        "referees_rows_updated": total_orgs_flipped,
    }

    _LOGGER.info("social_referral_status_ingestion_sweep_finished", summary=summary)
    return summary


@activity.defn(name="referral-status-list-pending-ingestion")
async def referral_status_list_pending_ingestion_activity() -> dict[str, Any]:
    @database_sync_to_async(thread_sensitive=True)
    def django_sync() -> dict[str, Any]:
        return build_pending_ingestion_snapshot()

    return await django_sync()


@activity.defn(name="referral-status-process-single-ingestion")
async def referral_status_process_single_ingestion_activity(inp: ProcessSingleReferralIngestionInput) -> dict[str, Any]:
    @database_sync_to_async(thread_sensitive=True)
    def django_sync() -> dict[str, Any]:
        return _flip_ingestion_for_referral(UUID(inp.social_referral_id))

    return await django_sync()


@activity.defn(name="referral-status-issue-shopify-codes")
async def referral_status_issue_shopify_codes_activity(inp: IssueShopifyCodesInput) -> list[ShopifyRewardEmailItem]:
    @database_sync_to_async(thread_sensitive=True)
    def django_sync() -> list[ShopifyRewardEmailItem]:
        return _issue_shopify_codes_for_referral_orgs(UUID(inp.social_referral_id), list(inp.flipped_org_keys))

    return await django_sync()


@activity.defn(name="referral-status-send-referral-ingestion-notice-emails")
def referral_status_send_referral_ingestion_notice_emails_activity(inp: SendReferralIngestionNoticeEmailsInput) -> None:
    _deliver_referral_shopify_reward_emails(UUID(inp.social_referral_id), list(inp.flipped_org_keys))


@activity.defn(name="referral-status-record-ingestion-check-failure")
async def referral_status_record_ingestion_check_failure_activity(inp: RecordIngestionCheckFailureInput) -> bool:
    @database_sync_to_async(thread_sensitive=True)
    def django_sync() -> bool:
        return record_ingestion_check_failure_on_referral_sync(UUID(inp.social_referral_id), inp.error_detail)

    return await django_sync()
