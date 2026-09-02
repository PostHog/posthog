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
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
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


class Command(BaseCommand):
    help = "Compute and persist an EnrichmentLabelResult for orgs missing one under the active prompt version."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--label", required=True, help="EnrichmentPromptConfig.name to run")
        parser.add_argument("--limit", type=int, default=None, help="Attempt at most this many (non-skipped) orgs")
        parser.add_argument("--workers", type=int, default=5, help="Bounded concurrency for LLM calls")
        parser.add_argument(
            "--max-failures",
            type=int,
            default=25,
            help="Abort the run once this many consecutive fetches fail in a row (circuit breaker)",
        )
        parser.add_argument(
            "--min-success-rate",
            type=float,
            default=0.5,
            help="Fail the run if succeeded/attempted drops below this fraction",
        )
        parser.add_argument(
            "--expected-version",
            default=None,
            help=(
                "If set, abort before spending if the label's current active version doesn't match. "
                "Guards a caller that resolved the active version separately (e.g. a scheduler deciding "
                "what to count as pending) against a version bump racing its own call."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        label: str = options["label"]
        limit: int | None = options["limit"]
        workers: int = options["workers"]
        max_failures: int = options["max_failures"]
        min_success_rate: float = options["min_success_rate"]
        expected_version: str | None = options["expected_version"]
        if workers < 1:
            raise CommandError("--workers must be at least 1")
        if limit is not None and limit < 1:
            raise CommandError("--limit must be at least 1")
        if max_failures < 1:
            raise CommandError("--max-failures must be at least 1")

        config = get_active_config(label)
        if config is None:
            raise CommandError(f"No active EnrichmentPromptConfig for label {label!r}")
        if expected_version is not None and config.version != expected_version:
            raise CommandError(
                f"label {label!r} active version is {config.version!r}, expected {expected_version!r}; "
                "the active version changed after the caller resolved it, aborting"
            )
        try:
            validate_input_fields(config)
            validate_output_fields(config)
        except PromptConfigError as e:
            raise CommandError(str(e)) from e

        lock_key = _advisory_lock_key(label)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_key])
            lock_acquired = cursor.fetchone()[0]
        if not lock_acquired:
            raise CommandError(f"Another enrichment_label_batch run already holds the lock for label {label!r}")

        try:
            self._run(label, config, limit, workers, max_failures, min_success_rate)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_key])

    def _run(
        self,
        label: str,
        config: EnrichmentPromptConfig,
        limit: int | None,
        workers: int,
        max_failures: int,
        min_success_rate: float,
    ) -> None:
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
            return (
                EnrichmentPromptConfig.objects.filter(pk=config.pk).values_list("name", flat=True).first()
                or config.name
            )

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
        summary = (
            f"attempted {counts['attempted']}, succeeded {counts['succeeded']}, "
            f"skipped_existing {counts['skipped_existing']}, "
            f"skipped_no_ai_consent {counts['skipped_no_ai_consent']}, unknown {counts['unknown']}, "
            f"failures {counts['failures']}, aborted {counts['aborted']}, "
            f"prompt_tokens {counts['prompt_tokens']}, completion_tokens {counts['completion_tokens']}, "
            f"elapsed_seconds {elapsed_seconds:.1f}"
        )
        logger.info(
            "enrichment_label_batch_complete",
            label=label,
            prompt_version=config.version,
            success_rate=success_rate,
            elapsed_seconds=elapsed_seconds,
            **counts,
        )
        # Written unconditionally, before any failure decision below: a wrapper parsing stdout
        # for these counts needs them most on the run that fails, not just on a clean one.
        self.stdout.write(summary)
        if circuit_open.is_set():
            raise CommandError(f"aborted after {max_failures} consecutive failures ({summary})")
        if tried > 0 and counts["succeeded"] == 0:
            raise CommandError(f"every attempted org failed ({summary})")
        if success_rate is not None and success_rate < min_success_rate:
            raise CommandError(
                f"success_rate {success_rate:.2f} is below --min-success-rate {min_success_rate} ({summary})"
            )
