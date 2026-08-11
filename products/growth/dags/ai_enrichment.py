"""Daily Dagster job driving AI enrichment classification for every active label.

`products/growth/backend/management/commands/enrichment_label_batch.py` is the classifier
engine: candidate selection, the per-label advisory lock, the ThreadPoolExecutor worker pool,
the consecutive-failure circuit breaker, and the success-rate gate all live there. This file
only schedules it — one op per run wraps `call_command("enrichment_label_batch", ...)` once
for every label with an active `EnrichmentPromptConfig`, so the command stays the single
source of truth for how a label actually gets classified.

Concurrency: labels are classified in a plain sequential loop inside one op, not fanned out
via `DynamicOutput.map()`. At any instant at most one label's command is running, so total
in-flight LLM calls are bounded by that command's own `--workers` (the same bound a manual
`enrichment_label_batch` run has) — never the sum across labels. `ee/billing/dags/
customer_archetype.py`'s cross-batch semaphore exists because batches for the *same* asset
run concurrently under its executor; nothing here runs concurrently, so that machinery would
add a lock with nothing to protect.

Spend bound: `--limit` (this module's `DEFAULT_LABEL_LIMIT`) caps attempted orgs per label
per run — see the PR description for the worst-case dollar arithmetic behind the default.

Absence-of-output check: a run that finds pending candidates but persists zero verdicts is
indistinguishable, from the command's own exit code, from a quiet day with nothing to do — a
zero-output pass through a working gateway looks identical to one where every call to it is
silently swallowed. `check_enrichment_run_op` re-counts candidates and verdicts itself and
raises if that happened, so the failure reaches #alerts-growth instead of going unnoticed.

Version pinning: a label's active version is resolved fresh inside `_run_one_label`, right
before counting and calling the command — never once for every label at op start. The op runs
labels sequentially and can take hours; resolving all versions up front and carrying them
across the whole loop would let a version bump for a label further down the list silently
detach the candidate count (still keyed to the old version) from what the command actually
writes (under whatever version is live when its turn comes up) — a real run reads as
`candidates > 0, created == 0` and false-alerts. `--expected-version` closes the remaining gap
between resolving here and the command resolving again for itself: if the two disagree, the
command aborts loudly as a command failure instead of a confusing silent one.

Environment: sends organization signup data to an external LLM gateway, so — like
`identity_matching.py` — it is not registered on Cloud EU.
"""

from dataclasses import dataclass

from django.conf import settings
from django.core.management import call_command

import dagster
import pydantic

from posthog.dags.common import JobOwners, skip_if_already_running
from posthog.exceptions_capture import capture_exception

from products.growth.backend.enrichment.labels import get_active_config, latest_fetches_qs
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig

# Roughly a day of signups plus headroom. This is the run's spend cap: see the PR description
# for the worst-case dollars-per-run arithmetic at this value.
DEFAULT_LABEL_LIMIT = 600

# Sequential across however many labels are active; generous relative to a single label's
# typical run so a slow gateway day doesn't trip it, but still short of Dagster run retention
# edge cases. ee/billing/dags/customer_archetype.py's weekly job (thousands of accounts) uses
# 12 hours; this job runs daily against a much smaller per-label cap, so a fraction of that
# is enough headroom.
MAX_RUNTIME_SECONDS = 6 * 60 * 60


def is_ai_enrichment_registered() -> bool:
    return settings.CLOUD_DEPLOYMENT != "EU"


class AiEnrichmentConfig(dagster.Config):
    limit: int = pydantic.Field(
        default=DEFAULT_LABEL_LIMIT,
        gt=0,
        description="Max orgs attempted per label per run — passed straight through to enrichment_label_batch --limit.",
    )
    workers: int = pydantic.Field(
        default=5,
        gt=0,
        description="Bounded concurrency for LLM calls within one label's run — passed through to --workers.",
    )


@dataclass(frozen=True, kw_only=True)
class LabelRunResult:
    label: str
    # None only when the label was active when listed but had no active config left by the time
    # _run_one_label got to it (deactivated, not merely bumped) — candidates/created are 0 in
    # that case and the command's own CommandError carries the failure.
    prompt_version: str | None
    candidates: int
    created: int
    error: str | None


def count_pending_candidates(label: str, prompt_version: str) -> int:
    """How many orgs the batch command would actually attempt for this label right now.

    Mirrors enrichment_label_batch's own targeting (latest fetch per org, minus one already
    holding a verdict under this exact label + prompt version) rather than importing its
    private `_attempt_targets` — that generator is a closure over the command's run-scoped
    counters and circuit breaker, not a reusable query. Also filters to AI-processing-approved
    orgs: the command enumerates a consent-declined org as "attempted" too, but never spends on
    it (see `ai_processing_approved` in enrichment/labels.py), so counting it here would make a
    day of nothing-but-declined-orgs look like a silent failure downstream.
    """
    latest_fetch_ids = latest_fetches_qs().values_list("id", flat=True)
    already_labeled = EnrichmentLabelResult.objects.filter(
        label_name=label, prompt_version=prompt_version, fetch_id__in=latest_fetch_ids
    ).values_list("fetch_id", flat=True)
    return (
        latest_fetches_qs()
        .exclude(id__in=already_labeled)
        .filter(organization__is_ai_data_processing_approved=True)
        .count()
    )


def _run_one_label(context: dagster.OpExecutionContext, *, label: str, limit: int, workers: int) -> LabelRunResult:
    """Resolves the label's active version itself, right here — not from a snapshot taken once
    for every label at op start. See the module docstring for why that distinction matters."""
    config = get_active_config(label)
    prompt_version = config.version if config is not None else None

    candidates = count_pending_candidates(label, prompt_version) if prompt_version is not None else 0
    before = (
        EnrichmentLabelResult.objects.filter(label_name=label, prompt_version=prompt_version).count()
        if prompt_version is not None
        else 0
    )

    error: str | None = None
    try:
        # expected_version=None when we couldn't resolve one either — the command's own
        # "No active EnrichmentPromptConfig" error already covers that case.
        call_command(
            "enrichment_label_batch", label=label, limit=limit, workers=workers, expected_version=prompt_version
        )
    except Exception as e:
        error = str(e)
        context.log.warning(f"enrichment_label_batch failed for label {label!r}: {e}")
        capture_exception(e, {"label": label, "prompt_version": prompt_version})

    created = (
        EnrichmentLabelResult.objects.filter(label_name=label, prompt_version=prompt_version).count() - before
        if prompt_version is not None
        else 0
    )
    context.log.info(f"label {label!r} ({prompt_version}): {candidates} candidates, {created} verdicts created")
    return LabelRunResult(
        label=label, prompt_version=prompt_version, candidates=candidates, created=created, error=error
    )


@dagster.op
def classify_pending_organizations_op(
    context: dagster.OpExecutionContext, config: AiEnrichmentConfig
) -> list[LabelRunResult]:
    """Run enrichment_label_batch once per active label, sequentially. See the module
    docstring for why this stays a plain loop instead of a DynamicOutput fan-out."""
    active_label_names = list(EnrichmentPromptConfig.objects.filter(is_active=True).values_list("name", flat=True))
    if not active_label_names:
        context.log.info("No active EnrichmentPromptConfig rows; nothing to classify")
        return []

    results = [
        _run_one_label(context, label=label, limit=config.limit, workers=config.workers) for label in active_label_names
    ]

    context.add_output_metadata(
        {
            "labels_processed": dagster.MetadataValue.int(len(results)),
            "total_candidates": dagster.MetadataValue.int(sum(r.candidates for r in results)),
            "total_created": dagster.MetadataValue.int(sum(r.created for r in results)),
        }
    )
    return results


@dagster.op
def check_enrichment_run_op(context: dagster.OpExecutionContext, results: list[LabelRunResult]) -> None:
    """Fail the run — and with it the job, routing to #alerts-growth — on either a command
    failure or a label that had pending candidates but produced no verdicts at all. A run that
    merely succeeds while classifying nothing raises nothing on its own; this is what makes
    that case loud instead of silent."""
    command_failures = [r for r in results if r.error is not None]
    silent_failures = [r for r in results if r.error is None and r.candidates > 0 and r.created == 0]
    if not command_failures and not silent_failures:
        context.log.info(f"ai_enrichment run OK: {len(results)} label(s) processed")
        return

    problems = [f"{r.label}: command failed ({r.error})" for r in command_failures]
    problems += [f"{r.label}: {r.candidates} candidates but 0 verdicts created" for r in silent_failures]
    raise dagster.Failure("ai_enrichment run had problems: " + "; ".join(problems))


@dagster.job(
    description="Daily job classifying pending organizations for every active AI enrichment label.",
    tags={"owner": JobOwners.TEAM_GROWTH.value, "dagster/max_runtime": str(MAX_RUNTIME_SECONDS)},
)
def ai_enrichment_job():
    check_enrichment_run_op(classify_pending_organizations_op())


@dagster.schedule(
    job=ai_enrichment_job,
    cron_schedule="0 7 * * *",
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.STOPPED,
)
@skip_if_already_running
def ai_enrichment_schedule(context: dagster.ScheduleEvaluationContext):
    # Never stack runs: enrichment_label_batch's own per-label advisory lock already refuses a
    # second concurrent run of the same label, but skipping here avoids paying for the
    # candidate-counting queries on a run that would fail immediately anyway.
    return dagster.RunRequest()
