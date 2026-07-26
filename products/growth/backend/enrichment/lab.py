"""Shared "score lab" runner pieces: the plumbing between the admin lab UI
(products/growth/backend/admin.py) and the staff API (products/growth/backend/api/score_lab.py).

Org-agnostic on purpose: everything here takes (config, payload/pair, client) in and a verdict
out. Callers build the input rows (which orgs, which fetches) themselves - see
products.growth.backend.enrichment.labels for recent_latest_fetches_qs /
signup_domain_for_organization, the internal row source both callers use.
"""

import re
import time
import asyncio
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAI

from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import classify_payload, classify_row
from products.growth.backend.models import EnrichmentPromptConfig, OrganizationEnrichmentFetch

# Runtime constraints only (the model keeps plain fields): curated gateway models and the
# archived-Harmonic payload paths worth feeding a prompt. Extend freely; stored rows with
# values outside these lists still render in the admin (choices are unioned with the instance's
# values there) but are rejected by the API's ChoiceField validation on run/save.
GATEWAY_MODEL_CHOICES = [
    "gpt-5.2",
    "gpt-5.2-pro",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]

HARMONIC_INPUT_FIELD_CHOICES = [
    ("name", "Company name"),
    ("description", "Description"),
    ("website.url", "Website URL"),
    ("companyType", "Company type"),
    ("headcount", "Headcount"),
    ("tagsV2", "Tags (tagsV2)"),
    ("funding.fundingStage", "Funding stage"),
    ("funding.fundingTotal", "Total funding"),
    ("funding.lastFundingAt", "Last funding date"),
    ("funding.investors", "Investors"),
    ("location.country", "Country"),
    ("foundingDate.date", "Founding date"),
]

# Single source of truth for the "new label" naming rule enforced on save by both the admin
# lab form and the staff API - a config with a name outside this shape can never be created,
# but existing rows and new versions of an existing label are unaffected.
LABEL_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Bounded so a lab run (admin dry-run or the staff API's /run/) stays a short request, not a
# batch job - and caps real LLM spend per call.
DEFAULT_SAMPLE_SIZE = 10
MAX_SAMPLE_SIZE = 100
DEFAULT_WORKERS = 5

_MODEL_LIST_CACHE_SECONDS = 300
# Module-level so a cold cache (first call, or one past its TTL) is shared across requests
# instead of re-fetched per request. Reset in tests via `_model_list_cache["models"] = None`.
_model_list_cache: dict[str, Any] = {"models": None, "expires_at": 0.0}


def list_gateway_models() -> list[str]:
    """Live gateway model ids (client.models.list()), cached for _MODEL_LIST_CACHE_SECONDS.

    Falls back to the curated GATEWAY_MODEL_CHOICES on ANY exception (gateway down,
    misconfigured credentials, a cold cache with no network) - this must never break run/save
    validation (see api/score_lab.py's model validation) or the /models/ endpoint. A fallback
    result is never cached, so the next call retries the gateway rather than sticking with the
    curated list for the full TTL.
    """
    now = time.monotonic()
    if _model_list_cache["models"] is not None and now < _model_list_cache["expires_at"]:
        return list(_model_list_cache["models"])
    try:
        client = get_llm_client(product="growth")
        models = sorted({model.id for model in client.models.list()})
        if not models:
            raise ValueError("gateway returned no models")
    except Exception:
        return list(GATEWAY_MODEL_CHOICES)
    _model_list_cache["models"] = models
    _model_list_cache["expires_at"] = now + _MODEL_LIST_CACHE_SECONDS
    return list(models)


def classify_pair(
    config: EnrichmentPromptConfig, pair: tuple[OrganizationEnrichmentFetch, str | None], client: OpenAI
) -> dict[str, Any]:
    fetch, signup_domain = pair
    company = fetch.payload.get("name") or fetch.organization.name
    try:
        verdict = classify_payload(config, fetch.payload, signup_domain, client)
    except Exception as e:
        return {
            "company": company,
            "domain": signup_domain,
            "verdict": "ERROR",
            "confidence": "-",
            "reasoning": str(e)[:200],
        }
    return {
        "company": company,
        "domain": signup_domain,
        "verdict": str(verdict.get(config.name)).lower(),
        "confidence": f"{verdict.get('confidence', 0.0):.2f}",
        "reasoning": verdict.get("reasoning", ""),
    }


async def stream_classifications(
    config: EnrichmentPromptConfig,
    inputs: list[tuple[OrganizationEnrichmentFetch, str | None]],
    client: OpenAI,
    workers: int = DEFAULT_WORKERS,
) -> AsyncIterator[dict[str, Any]]:
    """Classify each (fetch, signup_domain) pair concurrently, yielding one verdict as each completes.

    Async generator on purpose: under ASGI, Django fully buffers a sync iterator before
    sending anything, which silently defeats streaming. Shared by the admin changelist
    dry-run action, the admin lab run view, and the staff API's /run/ endpoint.
    """
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        tasks = [loop.run_in_executor(pool, classify_pair, config, pair, client) for pair in inputs]
        for task in asyncio.as_completed(tasks):
            yield await task
    finally:
        pool.shutdown(wait=False)


# (company, domain, output-or-None, error-or-None) for one classified item - the staff API's
# /run/ stream shape (api/score_lab.py), decoupled from any one input source so run() can drive
# it from either the archived-fetch path or the HogQL input_query path.
RunClassifyResult = tuple[str, str | None, dict[str, Any] | None, str | None]
RunClassifyFn = Callable[[EnrichmentPromptConfig, Any, OpenAI], RunClassifyResult]


def classify_fetch_for_run(
    config: EnrichmentPromptConfig, pair: tuple[OrganizationEnrichmentFetch, str | None], client: OpenAI
) -> RunClassifyResult:
    """RunClassifyFn for the archived-fetch input source."""
    fetch, signup_domain = pair
    company = fetch.payload.get("name") or fetch.organization.name
    try:
        output = classify_payload(config, fetch.payload, signup_domain, client)
    except Exception as e:
        return company, signup_domain, None, str(e)[:200]
    return company, signup_domain, output, None


def classify_row_for_run(config: EnrichmentPromptConfig, row: dict[str, Any], client: OpenAI) -> RunClassifyResult:
    """RunClassifyFn for the HogQL input_query source (see enrichment/input_query.py)."""
    company = row.get("company") or "Unknown"
    domain = row.get("domain")
    try:
        output = classify_row(config, row, client)
    except Exception as e:
        return company, domain, None, str(e)[:200]
    return company, domain, output, None


async def stream_run_classifications(
    config: EnrichmentPromptConfig,
    items: list[Any],
    classify_one: RunClassifyFn,
    client: OpenAI,
    workers: int = DEFAULT_WORKERS,
) -> AsyncIterator[RunClassifyResult]:
    """Like stream_classifications, but source-agnostic: `classify_one` is
    classify_fetch_for_run or classify_row_for_run depending on whether the run uses the
    archived-fetch or the input_query source. Used only by the staff API's /run/ endpoint."""
    loop = asyncio.get_running_loop()
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        tasks = [loop.run_in_executor(pool, classify_one, config, item, client) for item in items]
        for task in asyncio.as_completed(tasks):
            yield await task
    finally:
        pool.shutdown(wait=False)


def format_run_row(
    config: EnrichmentPromptConfig,
    company: str,
    domain: str | None,
    output: dict[str, Any] | None,
    error: str | None,
) -> dict[str, Any]:
    """Build one ndjson row for the staff API's /run/ stream (api/score_lab.py). A legacy
    config (no output_fields) keeps the historical flat {verdict, confidence, reasoning} shape;
    a configurable output schema nests values under "outputs" instead - see
    EnrichmentPromptConfig.output_fields."""
    if error is not None:
        if config.output_fields:
            return {"company": company, "domain": domain, "outputs": None, "error": error}
        return {"company": company, "domain": domain, "verdict": "ERROR", "confidence": "-", "reasoning": error}
    assert output is not None
    if config.output_fields:
        outputs = {field["key"]: output.get(field["key"]) for field in config.output_fields}
        return {"company": company, "domain": domain, "outputs": outputs}
    return {
        "company": company,
        "domain": domain,
        "verdict": str(output.get(config.name)).lower(),
        "confidence": f"{output.get('confidence', 0.0):.2f}",
        "reasoning": output.get("reasoning", ""),
    }
