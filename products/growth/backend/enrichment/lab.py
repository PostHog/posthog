"""Shared "score lab" runner pieces: the plumbing between the admin lab UI
(products/growth/backend/admin.py) and the staff API (products/growth/backend/api/score_lab.py).

Org-agnostic on purpose: everything here takes (config, payload/pair, client) in and a verdict
out. Callers build the input rows (which orgs, which fetches) themselves - see
products.growth.backend.enrichment.labels for recent_latest_fetches_qs /
signup_domain_for_organization, the internal row source both callers use.
"""

import re
import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAI

from products.growth.backend.enrichment.labels import classify_payload
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
