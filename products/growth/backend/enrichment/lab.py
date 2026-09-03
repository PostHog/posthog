"""Runner pieces behind the staff AI enrichment lab endpoints (products/growth/backend/api/ai_enrichment.py):
the gateway model list, and the concurrent stream that drives a test run.

Org-agnostic on purpose: everything here takes (config, fetch, client) in and a verdict out.
Callers build the input fetches themselves - see products.growth.backend.enrichment.labels for
recent_latest_fetches_qs / signup_domain_for_organization, the internal fetch source.
"""

import time
import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from django.db import close_old_connections, connection

import structlog
from openai import OpenAI

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import (
    ai_processing_approved,
    bound_inputs,
    classify_payload,
    extract_input_fields,
    unknown_output,
)
from products.growth.backend.models import EnrichmentPromptConfig, OrganizationEnrichmentFetch

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
