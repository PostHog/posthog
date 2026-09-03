"""Batched daily poller for Harmonic's async enrichment status.

Harmonic exposes exactly one signal for a stub it is still working on: an `enrichmentUrn` on
the lookup and a batchable `GET /enrichment_status` that returns QUEUED, IN_PROGRESS, COMPLETE,
FAILED or NOT_FOUND per URN, with no webhook. This workflow polls every org's most recently
archived open URN once a day, 50 URNs per Harmonic call, and stamps the result on
`OrganizationEnrichment.data` so the re-enrichment sweep and RevOps (`org_icp_fit_current`) can
read provider progress without polling anything themselves.
"""

import typing
import datetime as dt
import itertools
import dataclasses

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_regional_ph_client, ph_scoped_capture
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections
from posthog.utils import get_instance_region

from products.growth.backend.enrichment.writer import (
    HARMONIC_STATUS_AT_KEY,
    HARMONIC_STATUS_KEY,
    HARMONIC_URN_KEY,
    write_harmonic_enrichment_status,
)
from products.growth.backend.temporal.signup_enrichment.workflow import MAX_ENRICH_ATTEMPTS

LOGGER = get_logger(__name__)

STATUS_CHANGED_EVENT = "harmonic_enrichment_status_changed"
STATUS_POLL_RUN_EVENT = "harmonic_enrichment_status_poll_completed"

# STALLED is derived here; Harmonic never returns it.
NON_TERMINAL_STATUSES = ("QUEUED", "IN_PROGRESS")
TERMINAL_STATUSES = ("COMPLETE", "FAILED", "NOT_FOUND")
STALLED_STATUS = "STALLED"

# Harmonic's own guidance is "a few hours", so a URN still pending after 14 days is stamped
# STALLED so consumers can tell late from never. Stubs have completed after day 14, so polling
# continues to the 30-day cutoff below.
STALL_AGE_HOURS = 14 * 24

# Beyond this, the org's open URN is dropped from selection entirely and its stamp is left as
# whatever it last observed — a re-lookup issues a fresh URN, which restarts the window.
MAX_URN_AGE_DAYS = 30

# Harmonic caps URNs per /enrichment_status call.
POLL_BATCH_SIZE = 50

# A hard ceiling well under Temporal's per-payload limit, so a growing backlog degrades to a
# smaller nightly slice instead of one day failing outright.
MAX_CANDIDATES_PER_RUN = 5000

SELECT_ACTIVITY_TIMEOUT = dt.timedelta(minutes=5)
# One Harmonic HTTP call (10s client-side timeout) plus up to 50 row-locked record writes and a
# final analytics flush; generous headroom over the observed cost of either.
POLL_BATCH_ACTIVITY_TIMEOUT = dt.timedelta(seconds=60)


@dataclasses.dataclass(frozen=True)
class HarmonicStatusPollInputs:
    pass


@activity.defn
@close_db_connections
async def select_status_poll_candidates_activity(inputs: HarmonicStatusPollInputs) -> dict[str, typing.Any]:
    """Orgs due a status poll: an open URN under 30 days old, with no terminal stamp for it.

    Read-only, so guards live here rather than the schedule: a config flip takes effect on the
    next run without touching Temporal state, same as the sweep's selection.
    """
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    from posthog.models.instance_setting import get_instance_setting  # noqa: PLC0415

    from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch  # noqa: PLC0415

    logger = LOGGER.bind()

    if not await sync_to_async(get_instance_setting)("GROWTH_SIGNUP_ENRICHMENT_ENABLED"):
        logger.info("harmonic_status_poll_skipped_kill_switch")
        return {"candidates": [], "eligible": 0}
    if get_instance_region() not in ("US", "EU"):
        logger.info("harmonic_status_poll_skipped_region")
        return {"candidates": [], "eligible": 0}

    def _select() -> tuple[list[dict[str, typing.Any]], int]:
        now = dt.datetime.now(dt.UTC)
        urn_cutoff = now - dt.timedelta(days=MAX_URN_AGE_DAYS)

        # Same non-null-URN filter as core._latest_archived_urn, applied ahead of the DISTINCT ON
        # so a later fetch that archived a null URN (a recheck landing on an already-matched
        # company) can't shadow an earlier still-open tracking URN. Filtering the age cutoff here
        # too, rather than after, is equivalent: an org's latest qualifying row is its true latest
        # non-null-URN fetch only when that fetch itself is within the window — if it isn't, every
        # earlier one is even older, and the org has nothing left to select.
        latest_open_urn_fetches = (
            OrganizationEnrichmentFetch.objects.filter(
                provider="harmonic", payload__enrichmentUrn__isnull=False, fetched_at__gte=urn_cutoff
            )
            .exclude(payload__enrichmentUrn=None)
            .order_by("organization_id", "-fetched_at", "-id")
            .distinct("organization_id")
            .only("organization_id", "payload", "fetched_at")
        )

        open_urns: dict[str, tuple[str, dt.datetime]] = {}
        for row in latest_open_urn_fetches:
            urn = row.payload.get("enrichmentUrn") if isinstance(row.payload, dict) else None
            if isinstance(urn, str) and urn:
                open_urns[str(row.organization_id)] = (urn, row.fetched_at)

        if not open_urns:
            return [], 0

        stored = {
            str(record.organization_id): record.data
            for record in OrganizationEnrichment.objects.filter(organization_id__in=open_urns.keys()).only(
                "organization_id", "data"
            )
        }

        eligible = []
        for organization_id, (urn, fetched_at) in open_urns.items():
            data = stored.get(organization_id, {})
            stored_status = data.get(HARMONIC_STATUS_KEY)
            same_urn = data.get(HARMONIC_URN_KEY) == urn
            if stored_status in TERMINAL_STATUSES and same_urn:
                continue
            eligible.append(
                {
                    "organization_id": organization_id,
                    "enrichment_urn": urn,
                    "urn_fetched_at": fetched_at.isoformat(),
                    "previous_status": stored_status if same_urn else None,
                    "_never_polled": stored_status is None,
                    "_status_at": data.get(HARMONIC_STATUS_AT_KEY) or "",
                }
            )

        # Never-polled orgs go first so a backlog doesn't starve first contact; the rest is
        # oldest-checked-first so the cap doesn't repeatedly re-poll the same recently-checked orgs.
        eligible.sort(key=lambda candidate: (not candidate["_never_polled"], candidate["_status_at"]))
        candidates = [
            {key: value for key, value in candidate.items() if not key.startswith("_")}
            for candidate in eligible[:MAX_CANDIDATES_PER_RUN]
        ]
        return candidates, len(eligible)

    candidates, eligible_count = await sync_to_async(_select)()
    logger.info("harmonic_status_poll_selected", count=len(candidates), eligible=eligible_count)
    return {"candidates": candidates, "eligible": eligible_count}


@activity.defn
@close_db_connections
async def poll_status_batch_activity(candidates: list[dict[str, typing.Any]]) -> dict[str, typing.Any]:
    """One Harmonic status call for up to POLL_BATCH_SIZE URNs, then stamp and emit per org.

    Re-checks the kill switch here too, not just at selection: a run over many batches can span
    minutes, and this is the only gate between a flipped-off switch and further paid Harmonic
    calls, same rationale as the sweep's per-org recheck.
    """
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    from posthog.models.instance_setting import get_instance_setting  # noqa: PLC0415

    from products.growth.backend.enrichment.providers import HarmonicEnrichmentProvider  # noqa: PLC0415

    logger = LOGGER.bind()

    empty_result = {"polled": 0, "unobserved": 0, "changed": 0, "stalled": 0}

    if not await sync_to_async(get_instance_setting)("GROWTH_SIGNUP_ENRICHMENT_ENABLED"):
        logger.info("harmonic_status_poll_skipped_kill_switch")
        return dict(empty_result)

    pha_client = get_regional_ph_client()
    if pha_client is None:
        logger.error("harmonic_status_poll_no_regional_client")
        return dict(empty_result)

    polled = unobserved = changed = stalled = 0
    try:
        urns = [candidate["enrichment_urn"] for candidate in candidates]
        try:
            statuses = await HarmonicEnrichmentProvider().enrichment_statuses_for(urns)
        except Exception as e:
            capture_exception(e, {"batch_size": len(candidates)})
            raise

        now = dt.datetime.now(dt.UTC)
        observed_at = now.isoformat()

        for candidate in candidates:
            organization_id = candidate["organization_id"]
            urn = candidate["enrichment_urn"]
            raw_status = statuses.get(urn)
            if raw_status is None:
                # No entry back for this URN: leave the existing stamp alone rather than guess.
                unobserved += 1
                continue
            polled += 1

            urn_fetched_at = dt.datetime.fromisoformat(candidate["urn_fetched_at"])
            hours_since_urn_issued = round((now - urn_fetched_at).total_seconds() / 3600)
            effective_status = (
                STALLED_STATUS
                if raw_status in NON_TERMINAL_STATUSES and hours_since_urn_issued >= STALL_AGE_HOURS
                else raw_status
            )

            previous_status = await sync_to_async(write_harmonic_enrichment_status)(
                organization_id, status=effective_status, observed_at=observed_at, urn=urn, pha_client=pha_client
            )

            if effective_status == STALLED_STATUS:
                stalled += 1

            if effective_status != previous_status:
                changed += 1
                pha_client.capture(
                    distinct_id=organization_id,
                    event=STATUS_CHANGED_EVENT,
                    properties={
                        "organization_id": organization_id,
                        "previous_status": previous_status,
                        "status": effective_status,
                        "hours_since_urn_issued": hours_since_urn_issued,
                    },
                    groups={"organization": organization_id},
                )
    finally:
        pha_client.shutdown()

    logger.info(
        "harmonic_status_poll_batch_completed", polled=polled, unobserved=unobserved, changed=changed, stalled=stalled
    )
    return {"polled": polled, "unobserved": unobserved, "changed": changed, "stalled": stalled}


@dataclasses.dataclass(frozen=True)
class HarmonicStatusPollRunSummary:
    eligible: int
    selected: int
    polled: int
    unobserved: int
    changed: int
    stalled: int
    errors: int


@activity.defn
def report_status_poll_run_activity(summary: HarmonicStatusPollRunSummary) -> None:
    """One event per run, so an absence alert can see a poller that stopped firing."""
    region = get_instance_region()
    if region not in ("US", "EU"):
        LOGGER.error("harmonic_status_poll_no_regional_client")
        return

    with ph_scoped_capture(region=region) as capture:
        capture(
            distinct_id="harmonic-status-poller",
            event=STATUS_POLL_RUN_EVENT,
            properties=dataclasses.asdict(summary),
        )


@workflow.defn(name="harmonic-enrichment-status-poll")
class HarmonicEnrichmentStatusPollWorkflow(PostHogWorkflow):
    """Daily poll: select orgs with an open URN, batch-poll Harmonic, stamp transitions.

    Sequential batches, same reasoning as the sweep: trivially inside Harmonic's rate limit, and
    a failed batch (after its own retries) is logged and skipped rather than sinking the run —
    the next day's selection naturally re-offers anything still open.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> HarmonicStatusPollInputs:
        return HarmonicStatusPollInputs()

    @workflow.run
    async def run(self, inputs: HarmonicStatusPollInputs) -> dict[str, typing.Any]:
        selection = await workflow.execute_activity(
            select_status_poll_candidates_activity,
            inputs,
            start_to_close_timeout=SELECT_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        candidates = selection["candidates"]

        polled = unobserved = changed = stalled = errors = 0
        for batch in itertools.batched(candidates, POLL_BATCH_SIZE, strict=False):
            try:
                result = await workflow.execute_activity(
                    poll_status_batch_activity,
                    list(batch),
                    start_to_close_timeout=POLL_BATCH_ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(
                        maximum_attempts=MAX_ENRICH_ATTEMPTS, initial_interval=dt.timedelta(seconds=5)
                    ),
                )
                polled += result["polled"]
                unobserved += result["unobserved"]
                changed += result["changed"]
                stalled += result["stalled"]
            except Exception:
                # A batch's own retries are exhausted; one failed batch must not sink the whole run.
                errors += len(batch)

        summary = HarmonicStatusPollRunSummary(
            eligible=selection["eligible"],
            selected=len(candidates),
            polled=polled,
            unobserved=unobserved,
            changed=changed,
            stalled=stalled,
            errors=errors,
        )
        await workflow.execute_activity(
            report_status_poll_run_activity,
            summary,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return dataclasses.asdict(summary)
