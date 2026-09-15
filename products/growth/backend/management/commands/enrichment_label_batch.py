from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.facade import api, contracts


def _summary_line(summary: contracts.LabelBatchSummary) -> str:
    counts = summary.counts
    return (
        f"attempted {counts.attempted}, succeeded {counts.succeeded}, "
        f"skipped_existing {counts.skipped_existing}, "
        f"skipped_no_ai_consent {counts.skipped_no_ai_consent}, unknown {counts.unknown}, "
        f"failures {counts.failures}, aborted {counts.aborted}, "
        f"prompt_tokens {counts.prompt_tokens}, completion_tokens {counts.completion_tokens}, "
        f"elapsed_seconds {summary.elapsed_seconds:.1f}"
    )


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

        try:
            summary = api.run_label_batch(
                label, limit=limit, workers=workers, max_failures=max_failures, expected_version=expected_version
            )
        except contracts.GrowthEnrichmentError as e:
            raise CommandError(str(e)) from e

        line = _summary_line(summary)
        # Written unconditionally, before any failure decision below: a wrapper parsing stdout
        # for these counts needs them most on the run that fails, not just on a clean one.
        self.stdout.write(line)
        if summary.circuit_open:
            raise CommandError(f"aborted after {max_failures} consecutive failures ({line})")
        if summary.tried > 0 and summary.counts.succeeded == 0:
            raise CommandError(f"every attempted org failed ({line})")
        if summary.success_rate is not None and summary.success_rate < min_success_rate:
            raise CommandError(
                f"success_rate {summary.success_rate:.2f} is below --min-success-rate {min_success_rate} ({line})"
            )
