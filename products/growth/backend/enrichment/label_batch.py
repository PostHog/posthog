"""Shadow batch runner: computes an EnrichmentLabelResult for every org's latest fetch.

Idempotent and resumable — a killed or re-run pass skips any (org, label, version, fetch)
already computed, so partial progress is never redone and a re-enriched org naturally
recomputes under the same version. Nothing here is consumed downstream; results are
queryable in Postgres only.
"""

import time
import hashlib
import threading
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from uuid import UUID

from django.db import close_old_connections, connection, transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import (
    PromptConfigError,
    ai_processing_approved,
    classify_payload,
    get_active_config,
    is_unknown_output,
    latest_fetches_qs,
    signup_domain_for_organization,
    validate_input_fields,
    validate_output_fields,
)
from products.growth.backend.facade.contracts import (
    LabelBatchCounts,
    LabelBatchLocked,
    LabelBatchSummary,
    LabelConfigInvalid,
    LabelConfigNotFound,
    LabelVersionMismatch,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

logger = structlog.get_logger(__name__)

_ID_BATCH_SIZE = 500


def _advisory_lock_key(label: str) -> int:
    """Stable 64-bit key for pg_try_advisory_lock. The unique constraint on EnrichmentLabelResult
    stops a duplicate ROW, not the duplicate LLM spend — that happens minutes earlier, before the
    row is written — so two overlapping runs for the same label need a lock, not just the
    constraint."""
    digest = hashlib.sha256(f"enrichment_label_batch:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def run_label_batch(
    label: str,
    *,
    limit: int | None,
    workers: int,
    max_failures: int,
    expected_version: str | None,
) -> LabelBatchSummary:
    config = get_active_config(label)
    if config is None:
        raise LabelConfigNotFound(label)
    if expected_version is not None and config.version != expected_version:
        raise LabelVersionMismatch(label, config.version, expected_version)
    try:
        validate_input_fields(config)
        validate_output_fields(config)
    except PromptConfigError as e:
        raise LabelConfigInvalid(str(e)) from e

    lock_key = _advisory_lock_key(label)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_key])
        lock_acquired = cursor.fetchone()[0]
    if not lock_acquired:
        raise LabelBatchLocked(label)

    try:
        return _run(label, config, limit, workers, max_failures)
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_key])


def _run(
    label: str,
    config: EnrichmentPromptConfig,
    limit: int | None,
    workers: int,
    max_failures: int,
) -> LabelBatchSummary:
    started_at = time.monotonic()
    # tenacity in labels.py already owns retries (stop_after_attempt(3)); the SDK's own
    # internal retries underneath would multiply that budget nine-fold per fetch and actively
    # worsen a 429 the tenacity layer is already backing off from.
    client = get_llm_client(product="growth").with_options(max_retries=0)

    counts: dict[str, int] = {
        "attempted": 0,
        "succeeded": 0,
        "skipped_existing": 0,
        "skipped_no_ai_consent": 0,
        "unknown": 0,
        "failures": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        # Enumerated (counted into "attempted") but never processed because the circuit
        # breaker had already tripped — excluded from success_rate's denominator below so an
        # aborted run's ratio reflects what was actually tried, not what was merely queued.
        "aborted": 0,
        # A declined-at-enumeration-time org (the common case) never increments "attempted"
        # at all - see _attempt_targets. This one is for the rarer case _process's own
        # re-check catches: a fetch that WAS approved when enumerated (so "attempted" already
        # counted it) but got revoked before its own turn. Both cases add to
        # "skipped_no_ai_consent" for reporting; only this one needs subtracting out of
        # "attempted" below, or it would double-subtract.
        "consent_revoked_after_attempt": 0,
    }
    counts_lock = threading.Lock()
    failure_streak = 0
    circuit_open = threading.Event()

    def _result_exists(fetch: OrganizationEnrichmentFetch, label_name: str) -> bool:
        return EnrichmentLabelResult.objects.filter(
            organization_id=fetch.organization_id,
            label_name=label_name,
            prompt_version=config.version,
            fetch=fetch,
        ).exists()

    def _live_label_name() -> str:
        # A rename leaves content_hash alone, so the mid-run config check can't catch it. The
        # pre-spend check and the write both read the live name, or an existing verdict under
        # the renamed label fails to match and the fetch gets paid for twice.
        return EnrichmentPromptConfig.objects.filter(pk=config.pk).values_list("name", flat=True).first() or config.name

    # In-flight LLM concurrency is bounded by the pool size itself; no extra gate needed.
    def _process(fetch: OrganizationEnrichmentFetch, *, threaded: bool) -> None:
        nonlocal failure_streak
        if circuit_open.is_set():
            with counts_lock:
                counts["aborted"] += 1
            return
        try:
            if threaded:
                # Thread-local DB connections: drop any stale one before ORM work on this
                # thread. Kept inside the guarded region so a failure here counts as an
                # ordinary failure instead of escaping through future.result() and killing
                # the run — and closed again below, since pool threads are reused and
                # otherwise sit on a held connection for the full 60s of every LLM call.
                close_old_connections()
            # Re-check right before spending: another run may have computed this since the
            # target was enumerated.
            live_label = _live_label_name()
            if _result_exists(fetch, live_label):
                with counts_lock:
                    counts["skipped_existing"] += 1
                return
            if not ai_processing_approved(fetch.organization_id):
                # This fetch passed the enumeration-time check (or "attempted" wouldn't have
                # counted it) and got revoked between then and now - see
                # test_revoking_mid_run_is_honored_for_orgs_still_queued.
                with counts_lock:
                    counts["skipped_no_ai_consent"] += 1
                    counts["consent_revoked_after_attempt"] += 1
                return
            signup_domain = signup_domain_for_organization(fetch.organization)
            output = classify_payload(config, fetch.payload, signup_domain, client)
            # Popped rather than left inline: output is stored as-is, and duplicating the
            # inputs snapshot inside it would double-store and bloat every row.
            inputs = output.pop("inputs", {})
            with transaction.atomic():
                # Re-read: a rename can land while the LLM call is in flight, and stamping the
                # name captured before it would strand this verdict under a retired label.
                EnrichmentLabelResult.objects.get_or_create(
                    organization_id=fetch.organization_id,
                    fetch=fetch,
                    label_name=_live_label_name(),
                    prompt_version=config.version,
                    defaults={
                        "prompt_hash": config.content_hash,
                        "model": config.model,
                        "output": output,
                        "inputs": inputs,
                    },
                )
        except Exception as e:
            capture_exception(
                e,
                {
                    "organization_id": str(fetch.organization_id),
                    "label": label,
                    "prompt_version": config.version,
                },
            )
            with counts_lock:
                counts["failures"] += 1
                failure_streak += 1
                if failure_streak >= max_failures:
                    circuit_open.set()
            return
        finally:
            if threaded:
                connection.close()
        meta = output.get("meta", {})
        with counts_lock:
            counts["succeeded"] += 1
            counts["prompt_tokens"] += meta.get("prompt_tokens", 0)
            counts["completion_tokens"] += meta.get("completion_tokens", 0)
            failure_streak = 0
            if is_unknown_output(output):
                counts["unknown"] += 1

    def _id_batches() -> Iterator[list[tuple[UUID, UUID]]]:
        """Keyset-paginate latest_fetches_qs() over the full archive by organization_id in
        bounded chunks, so a multi-hour run never holds more than one page of full (payload +
        joined Organization) rows in memory. .iterator() alone doesn't guarantee that:
        DISABLE_SERVER_SIDE_CURSORS is true under pgbouncer, which silently degrades
        .iterator() to a client-side buffer that materializes the entire result set before
        yielding the first row.

        --limit is deliberately NOT enforced here: it bounds attempted (non-skipped) orgs, not
        enumerated ones, so it's applied in _attempt_targets instead. Capping the page query
        itself would make a resumed run re-enumerate the same already-processed prefix and
        attempt 0 forever whenever the first --limit orgs by organization_id already have a
        result."""
        last_org_id: UUID | None = None
        while True:
            id_qs = latest_fetches_qs().values_list("id", "organization_id")
            if last_org_id is not None:
                id_qs = id_qs.filter(organization_id__gt=last_org_id)
            page = list(id_qs[:_ID_BATCH_SIZE])
            if not page:
                return
            yield page
            last_org_id = page[-1][1]

    def _attempt_targets() -> Iterator[OrganizationEnrichmentFetch]:
        for page in _id_batches():
            if circuit_open.is_set():
                return
            fetches = OrganizationEnrichmentFetch.objects.filter(
                id__in=[fetch_id for fetch_id, _ in page]
            ).select_related("organization")
            for fetch in fetches:
                if circuit_open.is_set():
                    return
                if _result_exists(fetch, label):
                    with counts_lock:
                        counts["skipped_existing"] += 1
                    continue
                # Checked here, before the limit, and again in _process at spend-time: a
                # declined org costs nothing, so it must not consume a --limit slot - --limit
                # is a spend bound. Checking only at spend-time (the old behavior) let more
                # than --limit declined orgs ordered ahead of an approved one exhaust the
                # whole run without a single verdict written, which a consent-filtered
                # candidate count downstream (see products/growth/dags/ai_enrichment.py) can't
                # tell apart from a real failure. The spend-time re-check stays for a
                # revocation landing after this point but before that fetch's own turn (see
                # test_revoking_mid_run_is_honored_for_orgs_still_queued).
                if not ai_processing_approved(fetch.organization_id):
                    with counts_lock:
                        counts["skipped_no_ai_consent"] += 1
                    continue
                if limit is not None and counts["attempted"] >= limit:
                    return
                # Not lock-guarded: this generator is only ever driven by one thread at a time
                # (the serial loop, or the single submitting loop that feeds the pool below) —
                # unlike the counters _process mutates from worker threads.
                counts["attempted"] += 1
                yield fetch

    if workers == 1:
        # Serial path stays on the caller's DB connection — worker threads can't see an
        # open transaction (which is also why the tests run with --workers 1).
        for fetch in _attempt_targets():
            _process(fetch, threaded=False)
    else:
        # Bounded in-flight submission, and _id_batches keyset-paginates the driving query:
        # memory stays proportional to worker count and batch size, not archive size.
        pending: deque[Future[None]] = deque()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for fetch in _attempt_targets():
                pending.append(pool.submit(_process, fetch, threaded=True))
                if len(pending) >= workers * 4:
                    pending.popleft().result()
            while pending:
                pending.popleft().result()

    # succeeded/tried rather than a raw count: an alert can fire on the ratio, and on a run
    # that attempted nothing at all, which is what a silently broken input source looks like.
    # "tried" excludes aborted items so a circuit-broken run doesn't dilute the ratio with
    # work that was queued but never actually attempted. Consent skips are excluded for the
    # same reason (an archive of orgs that all declined is a correct empty run, not a failed
    # one), but only "consent_revoked_after_attempt" needs subtracting here - a declined org
    # caught at enumeration time never incremented "attempted" to begin with (see
    # _attempt_targets), so subtracting the full skipped_no_ai_consent count here would
    # double-subtract and could push "tried" negative.
    tried = counts["attempted"] - counts["aborted"] - counts["consent_revoked_after_attempt"]
    success_rate = counts["succeeded"] / tried if tried else None
    elapsed_seconds = time.monotonic() - started_at
    logger.info(
        "enrichment_label_batch_complete",
        label=label,
        prompt_version=config.version,
        success_rate=success_rate,
        elapsed_seconds=elapsed_seconds,
        **counts,
    )
    return LabelBatchSummary(
        label=label,
        prompt_version=config.version,
        counts=LabelBatchCounts(
            attempted=counts["attempted"],
            succeeded=counts["succeeded"],
            skipped_existing=counts["skipped_existing"],
            skipped_no_ai_consent=counts["skipped_no_ai_consent"],
            unknown=counts["unknown"],
            failures=counts["failures"],
            aborted=counts["aborted"],
            prompt_tokens=counts["prompt_tokens"],
            completion_tokens=counts["completion_tokens"],
        ),
        tried=tried,
        success_rate=success_rate,
        elapsed_seconds=elapsed_seconds,
        circuit_open=circuit_open.is_set(),
    )
