"""Runner pieces behind the staff score lab API (products/growth/backend/api/score_lab.py):
the gateway model list, classify_fetch_for_run, and the concurrent stream that drives it.

Org-agnostic on purpose: everything here takes (config, fetch, client) in and a verdict out.
Callers build the input fetches themselves - see products.growth.backend.enrichment.labels for
recent_latest_fetches_qs / signup_domain_for_organization, the internal fetch source.
"""

import re
import time
import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
from openai import OpenAI

from posthog.exceptions_capture import capture_exception
from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import classify_payload
from products.growth.backend.models import EnrichmentPromptConfig, OrganizationEnrichmentFetch

logger = structlog.get_logger(__name__)

# The archived-Harmonic payload paths a config may feed to a prompt, with the display name and
# value shape the picker shows. This is an allow-list, not a suggestion list: every value a config
# selects is sent to the LLM and then persisted to EnrichmentLabelResult.inputs indefinitely, so an
# arbitrary dotted path would be an open channel for whatever the provider happened to return.
# Served by GET /input_fields/ so the picker never hand-mirrors it. Extend freely.
HARMONIC_INPUT_FIELDS: list[dict[str, str]] = [
    {"value": "name", "label": "Company name", "type": "Text"},
    {"value": "description", "label": "Description", "type": "Text"},
    {"value": "website.url", "label": "Website URL", "type": "Text"},
    {"value": "companyType", "label": "Company type", "type": "Text"},
    {"value": "headcount", "label": "Headcount", "type": "Number"},
    {"value": "tagsV2", "label": "Tags (tagsV2)", "type": "List"},
    {"value": "funding.fundingStage", "label": "Funding stage", "type": "Text"},
    {"value": "funding.fundingTotal", "label": "Total funding", "type": "Number"},
    {"value": "funding.lastFundingAt", "label": "Last funding date", "type": "Date"},
    {"value": "funding.investors", "label": "Investors", "type": "List"},
    {"value": "location.country", "label": "Country", "type": "Text"},
    {"value": "foundingDate.date", "label": "Founding date", "type": "Date"},
]

HARMONIC_INPUT_FIELD_PATHS = [field["value"] for field in HARMONIC_INPUT_FIELDS]

# Single source of truth for the "new label" naming rule the staff API enforces on save - a
# config with a name outside this shape can never be created, but existing rows and new
# versions of an existing label are unaffected.
LABEL_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Bounded so a lab run (the staff API's /run/) stays a short request, not a batch job - and
# caps real LLM spend per call.
DEFAULT_SAMPLE_SIZE = 10
MAX_SAMPLE_SIZE = 100
DEFAULT_WORKERS = 5

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


# (company, domain, output-or-None, error-or-None) for one classified item - the staff API's
# /run/ stream shape (api/score_lab.py).
RunClassifyResult = tuple[str, str | None, dict[str, Any] | None, str | None]


def _run_error(config: EnrichmentPromptConfig, e: Exception, path: str) -> str:
    """Report the failure, and render it for the results table led by the exception type: an
    OpenAI SDK error's str() can carry the gateway URL and upstream response bodies."""
    capture_exception(e, {"label": config.name, "model": config.model, "path": path})
    return f"{type(e).__name__}: {str(e)[:120]}"


def classify_fetch_for_run(
    config: EnrichmentPromptConfig, pair: tuple[OrganizationEnrichmentFetch, str | None], client: OpenAI
) -> RunClassifyResult:
    fetch, signup_domain = pair
    company = fetch.payload.get("name") or fetch.organization.name
    try:
        output = classify_payload(config, fetch.payload, signup_domain, client)
    except Exception as e:
        return company, signup_domain, None, _run_error(config, e, "classify_fetch_for_run")
    return company, signup_domain, output, None


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
) -> dict[str, Any]:
    """Build one ndjson row for the staff API's /run/ stream (api/score_lab.py). Values are
    keyed by the config's output fields; the label name never appears in the data."""
    if error is not None:
        return {"company": company, "domain": domain, "outputs": None, "error": error}
    assert output is not None
    outputs = {field["key"]: output.get(field["key"]) for field in config.output_fields}
    return {"company": company, "domain": domain, "outputs": outputs}
