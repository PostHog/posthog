"""Shadow batch runner: computes an EnrichmentLabelResult for every org's latest fetch.

Idempotent and resumable — a killed or re-run pass skips any (org, label, version, fetch)
already computed, so partial progress is never redone and a re-enriched org naturally
recomputes under the same version. Nothing here is consumed downstream; results are
queryable in Postgres only.
"""

import threading
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import close_old_connections, transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import (
    UNKNOWN,
    classify_payload,
    get_active_config,
    latest_fetches_qs,
    signup_domain_for_organization,
    verdict_field_key,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = "Compute and persist an EnrichmentLabelResult for orgs missing one under the active prompt version."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--label", required=True, help="EnrichmentPromptConfig.name to run")
        parser.add_argument("--limit", type=int, default=None, help="Attempt at most this many (non-skipped) orgs")
        parser.add_argument("--workers", type=int, default=5, help="Bounded concurrency for LLM calls")

    def handle(self, *args: Any, **options: Any) -> None:
        label: str = options["label"]
        limit: int | None = options["limit"]
        workers: int = options["workers"]
        if workers < 1:
            raise CommandError("--workers must be at least 1")

        config = get_active_config(label)
        if config is None:
            raise CommandError(f"No active EnrichmentPromptConfig for label {label!r}")
        # A custom output schema's pass/fail key differs from `label` - see
        # verdict_field_key's docstring. Resolved once since config doesn't change mid-run.
        verdict_key = verdict_field_key(config)

        client = get_llm_client(product="growth")

        counts: dict[str, int] = {"attempted": 0, "succeeded": 0, "skipped_existing": 0, "unknown": 0, "failures": 0}
        counts_lock = threading.Lock()

        def _result_exists(fetch: OrganizationEnrichmentFetch) -> bool:
            return EnrichmentLabelResult.objects.filter(
                organization_id=fetch.organization_id,
                label_name=label,
                prompt_version=config.version,
                fetch=fetch,
            ).exists()

        # In-flight LLM concurrency is bounded by the pool size itself; no extra gate needed.
        def _process(fetch: OrganizationEnrichmentFetch) -> None:
            try:
                # Re-check right before spending: another run may have computed this since the
                # target was enumerated.
                if _result_exists(fetch):
                    with counts_lock:
                        counts["skipped_existing"] += 1
                    return
                signup_domain = signup_domain_for_organization(fetch.organization)
                output = classify_payload(config, fetch.payload, signup_domain, client)
                # Popped rather than left inline: output is stored as-is, and duplicating the
                # inputs snapshot inside it would double-store and bloat every row.
                inputs = output.pop("inputs", {})
                with transaction.atomic():
                    # Read the current name, not the one captured at startup: a label rename
                    # mid-run must stamp the retired result under the live name, or the next run
                    # for the renamed label would recompute the same fetch.
                    current_name = (
                        EnrichmentPromptConfig.objects.filter(pk=config.pk).values_list("name", flat=True).first()
                    )
                    EnrichmentLabelResult.objects.get_or_create(
                        organization_id=fetch.organization_id,
                        fetch=fetch,
                        label_name=current_name or config.name,
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
                return
            with counts_lock:
                counts["succeeded"] += 1
                if verdict_key is not None and output.get(verdict_key) == UNKNOWN:
                    counts["unknown"] += 1

        def _process_threaded(fetch: OrganizationEnrichmentFetch) -> None:
            # Thread-local DB connections: drop any stale one before ORM work on this thread.
            close_old_connections()
            _process(fetch)

        def _attempt_targets() -> Iterator[OrganizationEnrichmentFetch]:
            for fetch in latest_fetches_qs().select_related("organization").iterator():
                if limit is not None and counts["attempted"] >= limit:
                    return
                if _result_exists(fetch):
                    with counts_lock:
                        counts["skipped_existing"] += 1
                    continue
                counts["attempted"] += 1
                yield fetch

        if workers == 1:
            # Serial path stays on the caller's DB connection — worker threads can't see an
            # open transaction (which is also why the tests run with --workers 1).
            for fetch in _attempt_targets():
                _process(fetch)
        else:
            # Bounded in-flight submission: memory stays proportional to the worker count,
            # not the archive size.
            pending: deque[Future[None]] = deque()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for fetch in _attempt_targets():
                    pending.append(pool.submit(_process_threaded, fetch))
                    if len(pending) >= workers * 4:
                        pending.popleft().result()
                while pending:
                    pending.popleft().result()

        # succeeded/attempted rather than a raw count: an alert can fire on the ratio, and on a
        # run that attempted nothing at all, which is what a silently broken input source looks like.
        success_rate = counts["succeeded"] / counts["attempted"] if counts["attempted"] else None
        summary = (
            f"attempted {counts['attempted']}, succeeded {counts['succeeded']}, "
            f"skipped_existing {counts['skipped_existing']}, unknown {counts['unknown']}, failures {counts['failures']}"
        )
        logger.info(
            "enrichment_label_batch_complete",
            label=label,
            prompt_version=config.version,
            success_rate=success_rate,
            **counts,
        )
        if counts["failures"]:
            # Exiting 0 on a run where every item failed is indistinguishable from a clean run to
            # anything scheduling this.
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))
