"""Batched daily poller for Harmonic's async enrichment status.

Harmonic exposes exactly one signal for a stub it is still working on: an `enrichmentUrn` on
the lookup and a batchable `GET /enrichment_status` that returns QUEUED, IN_PROGRESS, COMPLETE,
FAILED or NOT_FOUND per URN, with no webhook. This workflow polls every org's most recently
archived open URN once a day, 50 URNs per Harmonic call, and stamps the result on
`OrganizationEnrichment.data` so the re-enrichment sweep (a later change) and RevOps
(`org_icp_fit_current`) can read provider progress without polling anything themselves.

See ~/dev/.claude/docs/enrichment/harmonic-urn-design-2026-08-26.md section 4.A (design) and
enrichment-architecture-current-2026-09-02.md S2 (the existing single-URN poll this reuses).

Runs as a Temporal Schedule (registered on deploy by signup_enrichment/schedule.py), about an
hour ahead of the re-enrichment sweep so the sweep's future status-aware selection reads a
same-day stamp. Selection re-checks the kill switch and region on every run, same as the sweep.
"""

import typing
import datetime as dt
import dataclasses

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import get_regional_ph_client, ph_scoped_capture
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import close_db_connections
from posthog.utils import get_instance_region

from products.growth.backend.enrichment.writer import ORGANIZATION_GROUP_TYPE
from products.growth.backend.temporal.signup_enrichment.workflow import MAX_ENRICH_ATTEMPTS

LOGGER = get_logger(__name__)

STATUS_CHANGED_EVENT = "harmonic_enrichment_status_changed"
STATUS_POLL_RUN_EVENT = "harmonic_enrichment_status_poll_completed"

# Record + org-group keys. Published in org_icp_fit_current (see
# org-icp-fit-current-view-2026-08-27.md); the names are the contract, not just an implementation
# detail, so they're spelled out as constants rather than inlined.
HARMONIC_STATUS_KEY = "harmonic_enrichment_status"
HARMONIC_STATUS_AT_KEY = "harmonic_enrichment_status_at"
HARMONIC_URN_KEY = "harmonic_enrichment_urn"

# Harmonic's own vocabulary, per console.harmonic.ai's enrich reference (cited in the design
# doc): QUEUED and IN_PROGRESS mean "check back later"; COMPLETE, FAILED and NOT_FOUND are
# terminal. STALLED is Growth's own derived state, never returned by Harmonic itself.
NON_TERMINAL_STATUSES = ("QUEUED", "IN_PROGRESS")
TERMINAL_STATUSES = ("COMPLETE", "FAILED", "NOT_FOUND")
STALLED_STATUS = "STALLED"

# Harmonic's own guidance is "a few hours", so a URN still pending after 14 days is stamped
# STALLED so consumers can tell late from never. Polling continues until the 30-day age-out
# below: the Aug 26 measurement saw stubs gain data at days 19 to 26.
STALL_AGE_HOURS = 14 * 24

# Beyond this, the org's open URN is dropped from selection entirely and its stamp is left as
# whatever it last observed — a re-lookup issues a fresh URN, which restarts the window.
MAX_URN_AGE_DAYS = 30

# Matches AsyncHarmonicClient's own internal batch size (ee/billing/salesforce_enrichment/
# harmonic_client.py:_ENRICHMENT_STATUS_BATCH_SIZE) so one activity call is exactly one Harmonic
# HTTP request, keeping batch-level retry/failure isolation meaningful.
POLL_BATCH_SIZE = 50

SELECT_ACTIVITY_TIMEOUT = dt.timedelta(minutes=5)
# One Harmonic HTTP call (10s client-side timeout) plus up to 50 row-locked record writes and a
# final analytics flush; generous headroom over the observed cost of either.
POLL_BATCH_ACTIVITY_TIMEOUT = dt.timedelta(seconds=60)


@dataclasses.dataclass(frozen=True)
class HarmonicStatusPollInputs:
    pass


@activity.defn
@close_db_connections
async def select_status_poll_candidates_activity(inputs: HarmonicStatusPollInputs) -> list[dict[str, typing.Any]]:
    """Orgs due a status poll: an open URN under 30 days old, with no terminal stamp.

    Read-only, so guards live here rather than the schedule: a config flip takes effect on the
    next run without touching Temporal state, same as the sweep's selection.
    """
    from asgiref.sync import sync_to_async  # noqa: PLC0415

    from posthog.models.instance_setting import get_instance_setting  # noqa: PLC0415

    from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch  # noqa: PLC0415

    logger = LOGGER.bind()

    if not await sync_to_async(get_instance_setting)("GROWTH_SIGNUP_ENRICHMENT_ENABLED"):
        logger.info("harmonic_status_poll_skipped_kill_switch")
        return []
    if get_instance_region() not in ("US", "EU"):
        logger.info("harmonic_status_poll_skipped_region")
        return []

    def _select() -> list[dict[str, typing.Any]]:
        now = dt.datetime.now(dt.UTC)
        urn_cutoff = now - dt.timedelta(days=MAX_URN_AGE_DAYS)

        # Same non-null-URN filter as core._latest_archived_urn, applied ahead of the DISTINCT ON
        # so a later fetch that archived a null URN (a recheck landing on an already-matched
        # company) can't shadow an earlier still-open tracking URN. Filtering the age cutoff here
        # too, rather than after, is equivalent: an org's latest qualifying row is its true latest
        # non-null-URN fetch only when that fetch itself is within the window — if it isn't, every
        # earlier one is even older, and the org has nothing left to select.
        # nosemgrep: orm-field-injection -- "enrichmentUrn" is a fixed field name, not user input
        latest_open_urn_fetches = (
            OrganizationEnrichmentFetch.objects.filter(payload__enrichmentUrn__isnull=False, fetched_at__gte=urn_cutoff)
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
            return []

        stored_statuses = {
            str(record.organization_id): record.data.get(HARMONIC_STATUS_KEY)
            for record in OrganizationEnrichment.objects.filter(organization_id__in=open_urns.keys()).only(
                "organization_id", "data"
            )
        }

        candidates = []
        for organization_id, (urn, fetched_at) in open_urns.items():
            status = stored_statuses.get(organization_id)
            if status in TERMINAL_STATUSES:
                continue
            candidates.append(
                {
                    "organization_id": organization_id,
                    "enrichment_urn": urn,
                    "urn_fetched_at": fetched_at.isoformat(),
                    "previous_status": status,
                }
            )
        return candidates

    candidates = await sync_to_async(_select)()
    logger.info("harmonic_status_poll_selected", count=len(candidates))
    return candidates


def _chunk(candidates: list[dict[str, typing.Any]], size: int) -> list[list[dict[str, typing.Any]]]:
    return [candidates[i : i + size] for i in range(0, len(candidates), size)]


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
    from products.growth.backend.enrichment.writer import merge_into_record  # noqa: PLC0415

    logger = LOGGER.bind()

    if not await sync_to_async(get_instance_setting)("GROWTH_SIGNUP_ENRICHMENT_ENABLED"):
        logger.info("harmonic_status_poll_skipped_kill_switch")
        return {"polled": 0, "changed": 0, "stalled": 0}

    pha_client = get_regional_ph_client()
    if pha_client is None:
        logger.error("harmonic_status_poll_no_regional_client")
        return {"polled": 0, "changed": 0, "stalled": 0}

    changed = stalled = 0
    try:
        urns = [candidate["enrichment_urn"] for candidate in candidates]
        try:
            statuses = await HarmonicEnrichmentProvider().enrichment_statuses_for(urns)
        except Exception as e:
            capture_exception(e, {"batch_size": len(candidates)})
            raise

        now = dt.datetime.now(dt.UTC)
        observed_at = now.isoformat()

        def _write(organization_id: str, urn: str, status: str) -> None:
            values = {HARMONIC_STATUS_KEY: status, HARMONIC_STATUS_AT_KEY: observed_at, HARMONIC_URN_KEY: urn}
            merge_into_record(organization_id, values)
            pha_client.group_identify(ORGANIZATION_GROUP_TYPE, organization_id, properties=values)

        for candidate in candidates:
            organization_id = candidate["organization_id"]
            urn = candidate["enrichment_urn"]
            raw_status = statuses.get(urn)
            if raw_status is None:
                # No entry back for this URN: leave the existing stamp alone rather than guess.
                continue

            urn_fetched_at = dt.datetime.fromisoformat(candidate["urn_fetched_at"])
            hours_since_urn_issued = round((now - urn_fetched_at).total_seconds() / 3600)
            effective_status = (
                STALLED_STATUS
                if raw_status in NON_TERMINAL_STATUSES and hours_since_urn_issued >= STALL_AGE_HOURS
                else raw_status
            )

            await sync_to_async(_write)(organization_id, urn, effective_status)

            if effective_status == STALLED_STATUS:
                stalled += 1

            previous_status = candidate["previous_status"]
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

    logger.info("harmonic_status_poll_batch_completed", polled=len(candidates), changed=changed, stalled=stalled)
    return {"polled": len(candidates), "changed": changed, "stalled": stalled}


@dataclasses.dataclass(frozen=True)
class HarmonicStatusPollRunSummary:
    selected: int
    polled: int
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
        candidates = await workflow.execute_activity(
            select_status_poll_candidates_activity,
            inputs,
            start_to_close_timeout=SELECT_ACTIVITY_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        polled = changed = stalled = errors = 0
        for batch in _chunk(candidates, POLL_BATCH_SIZE):
            try:
                result = await workflow.execute_activity(
                    poll_status_batch_activity,
                    batch,
                    start_to_close_timeout=POLL_BATCH_ACTIVITY_TIMEOUT,
                    retry_policy=RetryPolicy(
                        maximum_attempts=MAX_ENRICH_ATTEMPTS, initial_interval=dt.timedelta(seconds=5)
                    ),
                )
                polled += result["polled"]
                changed += result["changed"]
                stalled += result["stalled"]
            except Exception:
                # A batch's own retries are exhausted; capture_exception already ran inside the
                # activity. Count every org in it as unobserved and move on to the next batch —
                # one bad batch must not sink the whole run.
                errors += len(batch)

        summary = HarmonicStatusPollRunSummary(
            selected=len(candidates), polled=polled, changed=changed, stalled=stalled, errors=errors
        )
        await workflow.execute_activity(
            report_status_poll_run_activity,
            summary,
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return dataclasses.asdict(summary)
