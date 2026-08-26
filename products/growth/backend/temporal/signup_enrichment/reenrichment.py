"""Scheduled re-enrichment sweep for orgs whose V0.5 evaluation produced no score.

Measured on prod-us 2026-08-24 over 14,848 scored orgs: 40.8% of matched signups are
empty-shell Harmonic profiles (insufficient_data) and 0.9% aren't matched at all (not_found)
— mostly brand-new companies that accrete enrichment data over weeks, plus late Harmonic
indexing (the enrich mutation seeds async enrichment). The +4h recheck is too early for
either. This sweep re-runs the standard enrichment (fresh fetch, archive, transform, score)
for those orgs on a 30–90-day window:

- **30 days minimum** since the org's last sweep *attempt* (stamped on `OrganizationEnrichment.data`
  before the org reaches the provider, so a raised Harmonic error still counts): an org is
  retried at most every 30 days, and an unrelated fetch row from another command can't move
  this clock. An org the sweep has never attempted has no stamp, so its own last fetch stands
  in for one — without that it would be swept the morning after signup.
- **90 days maximum** since the org's first fetch: retries self-terminate (~2 per org) — an
  org still empty after two spaced retries stays at its honest status.

An org that Harmonic indexes after day 90 is never revisited. That is a deliberate ceiling,
not a backoff: `icp_reenrichment_attempt_count` is recorded but nothing reads it.

Runs as a Temporal Schedule (see the init_icp_reenrichment_schedule command) because the
Harmonic key lives on the workers only. Selection re-checks the kill switch and region on
every run, so flipping GROWTH_SIGNUP_ENRICHMENT_ENABLED off also stops the sweep. Each org
goes through `enrich_organization(is_recheck=True)` — same archive, same writers, same
person-mirror policy; the write-once at-signup snapshot and the launch signal are untouched
by construction (both live only in the signup activity). Emits `icp_reenrichment_completed`
per org so the sweep has its own health signal.
"""

import json
import typing
import datetime as dt
import dataclasses

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_regional_ph_client
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections

from products.growth.backend.temporal.signup_enrichment.workflow import ENRICH_ACTIVITY_TIMEOUT, MAX_ENRICH_ATTEMPTS

LOGGER = get_logger(__name__)

REENRICHMENT_EVENT = "icp_reenrichment_completed"

# Statuses the sweep retries. not_found is included on purpose: it doubles as recovery for
# late Harmonic indexing and for the match-bug population (pipeline-missed orgs).
SWEEPABLE_STATUSES = ("insufficient_data", "not_found")

MIN_DAYS_SINCE_LAST_ATTEMPT = 30
MAX_DAYS_SINCE_FIRST_FETCH = 90

# Stamped on every sweep attempt (see reenrich_organization_activity), not on a successful
# write — an archived fetch from an unrelated command (e.g. backfill_harmonic_ownership) or
# a raised Harmonic error must not silently move or freeze this org's retry clock.
ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY = "icp_reenrichment_last_attempted_at"
ICP_REENRICHMENT_ATTEMPT_COUNT_KEY = "icp_reenrichment_attempt_count"

# Selection is a handful of indexed queries; keep it snappy so a hung DB can't stall the
# scheduled run into its next occurrence.
SELECT_ACTIVITY_TIMEOUT = dt.timedelta(minutes=5)

# Same signup-membership window as backfill_signup_enrichment: the signup creator's
# membership lands within seconds of the org row, so an older earliest membership means the
# signup user left and nobody can stand in for the signup identity.
_SIGNUP_MEMBERSHIP_WINDOW = dt.timedelta(minutes=5)

# Orgs that fail identity filtering never get a new fetch row, so they'd otherwise re-occupy
# a cap slot on every run. Over-fetch the window so the cap can still be filled from what
# survives filtering, without making the query unbounded.
_SELECTION_OVERFETCH_MULTIPLIER = 3


@dataclasses.dataclass(frozen=True)
class IcpReenrichmentSweepInputs:
    # Overrides the GROWTH_ICP_REENRICH_DAILY_CAP setting when set (manual triggers).
    cap: typing.Optional[int] = None


@dataclasses.dataclass(frozen=True)
class ReenrichOrgInputs:
    organization_id: str
    distinct_id: str
    domain: str
    role_at_organization: typing.Optional[str] = None


@activity.defn
@close_db_connections
async def select_reenrichment_candidates_activity(inputs: IcpReenrichmentSweepInputs) -> list[dict[str, typing.Any]]:
    """Pick the orgs due a re-enrichment attempt, oldest-attempted-first, up to the daily cap.

    Guards live here rather than in the schedule so a config flip takes effect on the next
    run without touching Temporal state.
    """
    from django.conf import settings  # noqa: PLC0415 — heavy imports kept off the workflow module path
    from django.db.models import Max, Min, Q  # noqa: PLC0415

    from asgiref.sync import sync_to_async  # noqa: PLC0415

    from posthog.models.organization import OrganizationMembership  # noqa: PLC0415
    from posthog.utils import GenericEmails, get_instance_region  # noqa: PLC0415

    from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch  # noqa: PLC0415
    from products.growth.backend.temporal.signup_enrichment.trigger import domain_from_email  # noqa: PLC0415

    logger = LOGGER.bind()

    if not settings.GROWTH_SIGNUP_ENRICHMENT_ENABLED:
        logger.info("icp_reenrichment_skipped_kill_switch")
        return []
    if get_instance_region() not in ("US", "EU"):
        logger.info("icp_reenrichment_skipped_region")
        return []

    cap = inputs.cap if inputs.cap and inputs.cap > 0 else settings.GROWTH_ICP_REENRICH_DAILY_CAP
    generic_emails = GenericEmails()

    def _select() -> list[dict[str, typing.Any]]:
        now = dt.datetime.now(dt.UTC)
        attempt_cutoff = (now - dt.timedelta(days=MIN_DAYS_SINCE_LAST_ATTEMPT)).isoformat()
        first_fetch_cutoff = now - dt.timedelta(days=MAX_DAYS_SINCE_FIRST_FETCH)

        # JSONField key lookups return SQL NULL for a missing key, so a bare __lte would
        # silently drop never-attempted orgs instead of selecting them (same gotcha as
        # backfill_harmonic_ownership's has_key dance) — spell out "no key yet" explicitly.
        never_attempted = ~Q(data__has_key=ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY)
        # nosemgrep: orm-field-injection -- ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY is a module constant, not user input
        due_for_retry = Q(data__has_key=ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY) & Q(
            **{f"data__{ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY}__lte": attempt_cutoff}
        )
        attempt_eligible = {
            str(record.organization_id): record.data.get(ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY)
            for record in OrganizationEnrichment.objects.filter(data__icp_fit_status__in=list(SWEEPABLE_STATUSES))
            .filter(never_attempted | due_for_retry)
            .only("organization_id", "data")
        }

        first_fetches = (
            OrganizationEnrichmentFetch.objects.filter(organization_id__in=attempt_eligible.keys())
            .values("organization_id")
            .annotate(first_fetch=Min("fetched_at"), latest_fetch=Max("fetched_at"))
            .filter(first_fetch__gt=first_fetch_cutoff)
        )

        # A never-attempted org has no stamp for the 30-day minimum to measure, so without this
        # it is swept the morning after signup — the same too-early lookup the +4h recheck just
        # made. Its own last fetch stands in. Orgs that carry a stamp keep using it: the stamp
        # exists so an unrelated fetch row (a backfill) cannot move their retry clock.
        never_attempted_ids = {org_id for org_id, stamp in attempt_eligible.items() if stamp is None}
        fetch_cutoff = now - dt.timedelta(days=MIN_DAYS_SINCE_LAST_ATTEMPT)
        due_rows = [
            row
            for row in first_fetches
            if str(row["organization_id"]) not in never_attempted_ids or row["latest_fetch"] <= fetch_cutoff
        ]

        # Oldest-attempted-first, with never-attempted (None) sorting ahead of any
        # timestamp — an org the sweep hasn't touched yet is due before one it retried
        # last month.
        ordered_org_ids = sorted(
            (str(row["organization_id"]) for row in due_rows),
            key=lambda organization_id: attempt_eligible[organization_id] or "",
        )[: cap * _SELECTION_OVERFETCH_MULTIPLIER]

        roles = {
            str(record.organization_id): record.data.get("signup_role")
            for record in OrganizationEnrichment.objects.filter(organization_id__in=ordered_org_ids).only(
                "organization_id", "data"
            )
        }

        candidates: list[dict[str, typing.Any]] = []
        for organization_id in ordered_org_ids:
            membership = (
                OrganizationMembership.objects.filter(organization_id=organization_id)
                .select_related("user", "organization")
                .order_by("joined_at")
                .first()
            )
            if membership is None or membership.user is None:
                continue
            if membership.joined_at - membership.organization.created_at > _SIGNUP_MEMBERSHIP_WINDOW:
                continue  # signup user left; nobody can stand in for the signup identity
            user = membership.user
            domain = domain_from_email(user.email) if user.email else None
            if not user.distinct_id or not domain or generic_emails.is_generic(user.email):
                continue
            candidates.append(
                {
                    "organization_id": organization_id,
                    "distinct_id": user.distinct_id,
                    "domain": domain,
                    "role_at_organization": roles.get(organization_id),
                }
            )
            if len(candidates) >= cap:
                break
        return candidates

    candidates = await sync_to_async(_select)()
    logger.info("icp_reenrichment_selected", count=len(candidates), cap=cap)
    return candidates


@activity.defn
@close_db_connections
async def reenrich_organization_activity(inputs: ReenrichOrgInputs) -> dict[str, typing.Any]:
    """One org through the standard enrichment path, recheck-style, with its own event."""
    from django.conf import settings  # noqa: PLC0415 — heavy imports kept off the workflow module path

    from asgiref.sync import sync_to_async  # noqa: PLC0415

    from posthog.models.organization import Organization  # noqa: PLC0415

    from products.growth.backend.enrichment.core import enrich_organization  # noqa: PLC0415
    from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider  # noqa: PLC0415
    from products.growth.backend.enrichment.writer import merge_into_record  # noqa: PLC0415

    logger = LOGGER.bind(organization_id=inputs.organization_id)

    # Re-checked here, not just at selection: a run can span hours, and this is the only
    # gate standing between a flipped-off switch and further paid Harmonic calls.
    if not settings.GROWTH_SIGNUP_ENRICHMENT_ENABLED:
        logger.info("icp_reenrichment_skipped_kill_switch")
        return {"matched": False, "skipped": "kill_switch"}

    # Selection can be hours stale by the tail of a run, and the enrichment FKs skip DB
    # constraints — without this recheck, an org deleted mid-sweep would get its rows and
    # group properties recreated right after the deletion cascade removed them.
    if not await sync_to_async(Organization.objects.filter(id=inputs.organization_id).exists)():
        logger.info("icp_reenrichment_skipped_org_deleted")
        return {"matched": False, "skipped": "organization_deleted"}

    # Stamped before the org reaches the provider so a raised Harmonic error still counts
    # as an attempt — otherwise a failing org never gets a fetch row and re-occupies the
    # head of tomorrow's selection, burning another MAX_ENRICH_ATTEMPTS Harmonic calls.
    attempted_at = dt.datetime.now(dt.UTC).isoformat()

    def _stamp_attempt(current: dict[str, typing.Any]) -> dict[str, typing.Any]:
        return {
            ICP_REENRICHMENT_LAST_ATTEMPTED_AT_KEY: attempted_at,
            ICP_REENRICHMENT_ATTEMPT_COUNT_KEY: current.get(ICP_REENRICHMENT_ATTEMPT_COUNT_KEY, 0) + 1,
        }

    await sync_to_async(merge_into_record)(inputs.organization_id, _stamp_attempt)

    pha_client = get_regional_ph_client()
    if pha_client is None:
        logger.error("icp_reenrichment_no_regional_client")
        return {"matched": False}

    try:
        outcome = await enrich_organization(
            organization_id=inputs.organization_id,
            domain=inputs.domain,
            provider=HarmonicEnrichmentProvider(),
            pha_client=pha_client,
            is_recheck=True,
            role_at_organization=inputs.role_at_organization,
            distinct_id=inputs.distinct_id,
        )
        matched = outcome.provider_fields is not None
        status = outcome.fit.status if outcome.fit else None
        pha_client.capture(
            distinct_id=inputs.distinct_id,
            event=REENRICHMENT_EVENT,
            properties={
                "organization_id": inputs.organization_id,
                "matched": matched,
                "icp_fit_status": status,
            },
            groups={"organization": inputs.organization_id},
        )
        logger.info("icp_reenrichment_completed", matched=matched, icp_fit_status=status)
        return {"matched": matched, "icp_fit_status": status}
    except Exception as e:
        capture_exception(e)
        raise
    finally:
        pha_client.shutdown()


@workflow.defn(name="icp-reenrichment-sweep")
class IcpReenrichmentSweepWorkflow(PostHogWorkflow):
    """Daily sweep: select due orgs, then re-enrich them one at a time.

    Sequential on purpose — the per-call rate stays trivially inside Harmonic's limit, and
    at the default cap (500) a full run is well under two hours, far inside a daily
    schedule. A failed org (after the per-org retries) is logged and skipped: the window
    query naturally re-offers it next run if it stays eligible.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> IcpReenrichmentSweepInputs:
        if not inputs:
            return IcpReenrichmentSweepInputs()
        return IcpReenrichmentSweepInputs(**json.loads(inputs[0]))

    @workflow.run
    async def run(self, inputs: IcpReenrichmentSweepInputs) -> dict[str, typing.Any]:
        candidates = await workflow.execute_activity(
            select_reenrichment_candidates_activity,
            inputs,
            start_to_close_timeout=SELECT_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        attempted = matched = failed = 0
        for candidate in candidates:
            attempted += 1
            try:
                result = await workflow.execute_activity(
                    reenrich_organization_activity,
                    ReenrichOrgInputs(**candidate),
                    start_to_close_timeout=ENRICH_ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(
                        maximum_attempts=MAX_ENRICH_ATTEMPTS, initial_interval=dt.timedelta(seconds=5)
                    ),
                )
                if result.get("matched"):
                    matched += 1
            except Exception:
                # Per-org failures must not sink the sweep; the org stays eligible next run.
                failed += 1

        return {"selected": len(candidates), "attempted": attempted, "matched": matched, "failed": failed}
