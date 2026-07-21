"""Shadow batch runner: computes an EnrichmentLabelResult for every org's latest fetch.

Idempotent and resumable — a killed or re-run pass skips any (org, label, version, fetch)
already computed, so partial progress is never redone and a re-enriched org naturally
recomputes under the same version. Nothing here is consumed downstream; results are
queryable in Postgres only.
"""

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import close_old_connections

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import (
    UNKNOWN,
    classify_payload,
    latest_fetches_qs,
    signup_email_for_organization,
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

        config = EnrichmentPromptConfig.objects.filter(name=label, is_active=True).first()
        if config is None:
            raise CommandError(f"No active EnrichmentPromptConfig for label {label!r}")

        client = get_llm_client(product="growth")
        semaphore = threading.Semaphore(workers)

        counts: dict[str, int] = {"attempted": 0, "succeeded": 0, "skipped_existing": 0, "unknown": 0, "failures": 0}
        counts_lock = threading.Lock()

        def _process(fetch: OrganizationEnrichmentFetch) -> None:
            with semaphore:
                try:
                    email = signup_email_for_organization(fetch.organization)
                    output = classify_payload(config, fetch.payload, email, client)
                    EnrichmentLabelResult.objects.get_or_create(
                        organization_id=fetch.organization_id,
                        fetch=fetch,
                        label_name=label,
                        prompt_version=config.version,
                        defaults={"prompt_hash": config.content_hash, "model": config.model, "output": output},
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
                if output.get("ai_pilled") == UNKNOWN:
                    counts["unknown"] += 1

        def _process_threaded(fetch: OrganizationEnrichmentFetch) -> None:
            # Thread-local DB connections: drop any stale one before ORM work on this thread.
            close_old_connections()
            _process(fetch)

        def _attempt_targets() -> Iterator[OrganizationEnrichmentFetch]:
            for fetch in latest_fetches_qs().select_related("organization").iterator():
                if limit is not None and counts["attempted"] >= limit:
                    return
                exists = EnrichmentLabelResult.objects.filter(
                    organization_id=fetch.organization_id,
                    label_name=label,
                    prompt_version=config.version,
                    fetch=fetch,
                ).exists()
                if exists:
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
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_process_threaded, fetch) for fetch in _attempt_targets()]
                for future in futures:
                    future.result()

        summary = (
            f"attempted {counts['attempted']}, succeeded {counts['succeeded']}, "
            f"skipped_existing {counts['skipped_existing']}, unknown {counts['unknown']}, failures {counts['failures']}"
        )
        self.stdout.write(self.style.SUCCESS(summary) if counts["failures"] == 0 else self.style.WARNING(summary))
        logger.info("enrichment_label_batch_complete", label=label, prompt_version=config.version, **counts)
