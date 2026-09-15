"""Runner pieces behind the staff AI enrichment lab endpoints (products/growth/backend/api/ai_enrichment.py):
the gateway model list, and the concurrent stream that drives a test run. Also the sequential
sample run behind the enrichment_label_dry_run command, which persists nothing.

The endpoint runners are org-agnostic on purpose: they take (config, fetch, client) in and a verdict
out. Their callers build the input fetches themselves - see products.growth.backend.enrichment.labels for
recent_latest_fetches_qs / signup_domain_for_organization, the internal fetch source.
"""

import time
import asyncio
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from django.db import close_old_connections, connection

import structlog
from openai import OpenAI

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import (
    PromptConfigError,
    ai_processing_approved,
    bound_inputs,
    classify_payload,
    extract_input_fields,
    get_active_config,
    recent_latest_fetches_qs,
    signup_domain_for_organization,
    unknown_output,
    validate_input_fields,
    validate_output_fields,
    verdict_field_key,
)
from products.growth.backend.facade.contracts import (
    LabelCompareVersionNotFound,
    LabelConfigInvalid,
    LabelConfigNotFound,
    LabelDryRun,
    LabelDryRunRow,
    LabelOutputField,
    LabelPromptFileUnreadable,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

logger = structlog.get_logger(__name__)

# Bounded so a test run (the staff API's /run/) stays a short request, not a batch job - and
# caps real LLM spend per call.
DEFAULT_SAMPLE_SIZE = 5
MAX_SAMPLE_SIZE = 10
DEFAULT_WORKERS = 5

# The version stamped on the in-memory, unsaved config a /run/ test-run classifies against - never
# persisted, so it never collides with a real saved version string. Also rejected as a
# caller-supplied version on /save/ (ai_enrichment_serializers.py), so a client can't accidentally
# freeze a row that then reads as an in-flight draft.
DRAFT_VERSION_SENTINEL = "lab-draft"

_MODEL_LIST_CACHE_SECONDS = 300
# Module-level so a cold cache (first call, or one past its TTL) is shared across requests
# instead of re-fetched per request. Reset in tests via `_model_list_cache["models"] = None`.
_model_list_cache: dict[str, Any] = {"models": None, "expires_at": 0.0}


def list_gateway_models() -> list[str]:
    """Live gateway model ids (client.models.list()), cached for _MODEL_LIST_CACHE_SECONDS.

    Returns an empty list on ANY exception rather than falling back to a curated copy. The
    gateway is the source of truth, and a hand-maintained mirror goes stale silently: it keeps
    offering models the gateway has dropped and hides ones it has added, with no signal either
    way. Same reasoning as products/slack_app/backend/services/llm_models.py. An empty result is
    never cached, so the next call retries immediately.
    """
    now = time.monotonic()
    if _model_list_cache["models"] is not None and now < _model_list_cache["expires_at"]:
        return list(_model_list_cache["models"])
    try:
        client = get_llm_client(product="growth")
        models = sorted({model.id for model in client.models.list()})
        if not models:
            raise ValueError("gateway returned no models")
    except Exception as e:
        # This failure empties the model picker with no other symptom, so it has to reach error
        # tracking rather than only a log line nobody reads.
        capture_exception(e, {"path": "list_gateway_models"})
        return []
    _model_list_cache["models"] = models
    _model_list_cache["expires_at"] = now + _MODEL_LIST_CACHE_SECONDS
    return list(models)


# (company, domain, output-or-None, error-or-None, inputs-sent) for one classified item - the
# staff API's /run/ stream shape (api/ai_enrichment.py). `inputs` is populated on both the success
# and the error path (see classify_fetch_for_run) - a row that failed the LLM call still shows
# what would have been sent, since extraction happens before that call either way.
RunClassifyResult = tuple[str, str | None, dict[str, Any] | None, str | None, dict[str, Any]]


def _run_error(config: EnrichmentPromptConfig, e: Exception, path: str) -> str:
    """Report the failure, and render it for the results table led by the exception type: an
    OpenAI SDK error's str() can carry the gateway URL and upstream response bodies. The 2000-char
    cap is ours, not upstream's - generous enough that the frontend's error-tooltip rarely
    truncates mid-sentence, while still bounded against a pathological upstream error body."""
    capture_exception(e, {"label": config.name, "model": config.model, "path": path})
    return f"{type(e).__name__}: {str(e)[:2000]}"


def classify_fetch_for_run(
    config: EnrichmentPromptConfig, pair: tuple[OrganizationEnrichmentFetch, str | None], client: OpenAI
) -> RunClassifyResult:
    fetch, signup_domain = pair
    company = fetch.payload.get("name") or fetch.organization.name
    # Computed up front, independent of the try/except below: classify_payload only returns this
    # (nested in output["inputs"]) on success, and re-deriving it here - cheap, pure extraction,
    # no LLM call - is simpler than threading a partial result out of a caught exception. Without
    # it, a row that fails the LLM call would show an empty "inputs sent" despite having built one.
    # Mirrors classify_payload's own short-circuit for a missing/not-found archived payload
    # (`{"companyFound": False}`, or no payload at all): it never extracts from one, so a row for
    # one must not display inputs the classifier never touched.
    if not fetch.payload or fetch.payload.get("companyFound") is False:
        inputs: dict[str, Any] = {}
    else:
        inputs = bound_inputs(extract_input_fields(fetch.payload, config.input_fields))
    try:
        # Thread-local DB connection: drop any stale one left by this pool thread's previous
        # iteration before the consent recheck query below - same pattern as
        # enrichment_label_batch.py's threaded worker. Closed again in `finally` so it isn't held
        # open past this iteration, into this worker thread's next one.
        close_old_connections()
        # Re-checked here, not just at the prefetch filter in _build_run_inputs: a run streams
        # over several seconds to minutes, long enough for an admin to revoke consent mid-run. A
        # stale approval read before streaming started must not still reach the LLM.
        if not ai_processing_approved(fetch.organization_id):
            output = unknown_output(config, signup_domain, "AI processing consent was revoked mid-run")
            return company, signup_domain, output, None, {}
        output = classify_payload(config, fetch.payload, signup_domain, client)
    except Exception as e:
        return company, signup_domain, None, _run_error(config, e, "classify_fetch_for_run"), inputs
    finally:
        connection.close()
    return company, signup_domain, output, None, inputs


async def stream_run_classifications(
    config: EnrichmentPromptConfig,
    items: list[tuple[OrganizationEnrichmentFetch, str | None]],
    client: OpenAI,
    workers: int = DEFAULT_WORKERS,
) -> AsyncIterator[RunClassifyResult]:
    """Classify each archived fetch concurrently, yielding one result as each completes.

    Async generator on purpose: under ASGI, Django fully buffers a sync iterator before sending
    anything, which silently defeats streaming."""
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        tasks = [loop.run_in_executor(pool, classify_fetch_for_run, config, item, client) for item in items]
        for task in asyncio.as_completed(tasks):
            yield await task
    finally:
        # cancel_futures so a client disconnect stops paying for calls that haven't started yet.
        pool.shutdown(wait=False, cancel_futures=True)


def format_run_row(
    config: EnrichmentPromptConfig,
    company: str,
    domain: str | None,
    output: dict[str, Any] | None,
    error: str | None,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Build one ndjson row for the staff API's /run/ stream (api/ai_enrichment.py). Values are
    keyed by the config's output fields; the label name never appears in the data. `inputs` is
    what was actually sent to the LLM (post to_domain/bound_inputs reduction) - surfaced so a
    staff user can see why a verdict came out the way it did without re-running the query, and
    populated on an error row too (see classify_fetch_for_run). `meta` carries classify_payload's
    provenance dict verbatim (see labels.py's is_unknown_output) - the frontend prefers
    `meta.skipped` over sniffing individual values for the literal "unknown" string, since a
    schema with no boolean output field never writes that sentinel into any value at all.
    """
    if error is not None:
        return {"company": company, "domain": domain, "inputs": inputs, "outputs": None, "error": error}
    assert output is not None
    outputs = {field["key"]: output.get(field["key"]) for field in config.output_fields}
    return {"company": company, "domain": domain, "inputs": inputs, "outputs": outputs, "meta": output.get("meta", {})}


def _output_fields(config: EnrichmentPromptConfig) -> tuple[LabelOutputField, ...]:
    return tuple(LabelOutputField(key=field["key"], type=field["type"]) for field in config.output_fields)


def dry_run(label: str, *, sample: int, prompt_file: str | None, compare_version: str | None) -> LabelDryRun:
    config = get_active_config(label)
    if config is None:
        raise LabelConfigNotFound(label)
    try:
        validate_input_fields(config)
        validate_output_fields(config)
    except PromptConfigError as e:
        raise LabelConfigInvalid(str(e)) from e

    display_version = config.version
    if prompt_file:
        try:
            config.prompt_text = Path(prompt_file).read_text()
        except OSError as e:
            raise LabelPromptFileUnreadable(prompt_file, e) from e
        # Never saved — an in-memory override for iteration, not a new version.
        display_version = f"{config.version}+file"

    # tenacity in labels.py already owns retries; the SDK's own internal retries underneath
    # would multiply that budget nine-fold per row.
    client = get_llm_client(product="growth").with_options(max_retries=0)

    compare_config: EnrichmentPromptConfig | None = None
    if compare_version:
        compare_config = EnrichmentPromptConfig.objects.filter(name=label, version=compare_version).first()
        if compare_config is None:
            raise LabelCompareVersionNotFound(label, compare_version)

    fetches = list(recent_latest_fetches_qs().select_related("organization")[:sample])
    return LabelDryRun(
        display_version=display_version,
        # A custom output schema's pass/fail key differs from `label` - see verdict_field_key's docstring.
        verdict_key=verdict_field_key(config),
        output_fields=_output_fields(config),
        compare_output_fields=_output_fields(compare_config) if compare_config is not None else None,
        rows=_dry_run_rows(
            config,
            fetches,
            client,
            label=label,
            compare_version=compare_version if compare_config is not None else None,
        ),
    )


def _dry_run_rows(
    config: EnrichmentPromptConfig,
    fetches: list[OrganizationEnrichmentFetch],
    client: OpenAI,
    *,
    label: str,
    compare_version: str | None,
) -> Iterator[LabelDryRunRow]:
    for fetch in fetches:
        # Its own outcome rather than an error: a declined org is a correct result, and counting it
        # as an error would trip the every-row-failed check.
        if not ai_processing_approved(fetch.organization_id):
            yield LabelDryRunRow(company=fetch.organization.name, skipped_no_ai_consent=True)
            continue
        try:
            # Inside the guard too: an archived payload that isn't a dict (classify_payload
            # already tolerates this) must produce one error row, not end the whole sample.
            company = fetch.payload.get("name") or fetch.organization.name
            signup_domain = signup_domain_for_organization(fetch.organization)
            output = classify_payload(config, fetch.payload, signup_domain, client)
        except Exception as e:
            yield LabelDryRunRow(company=fetch.organization.name, error=str(e))
            continue

        prior_output = None
        if compare_version is not None:
            prior = (
                EnrichmentLabelResult.objects.filter(
                    organization_id=fetch.organization_id, label_name=label, prompt_version=compare_version
                )
                .order_by("-created_at")
                .first()
            )
            prior_output = prior.output if prior is not None else {}
        yield LabelDryRunRow(company=company, signup_domain=signup_domain, output=output, prior_output=prior_output)
