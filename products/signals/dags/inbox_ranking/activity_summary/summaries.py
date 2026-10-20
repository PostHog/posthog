"""The LLM step behind `activity_summaries`: one call per inputs row, its cost, and its event.

The call goes through `build_openai_client`, so the deployment picks the gateway: the Go AI gateway
when its settings are set, else the Python gateway on the `signals` route.
"""

import json
import time
import datetime
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import build_openai_client, trace_id_from_seed

from products.signals.dags.inbox_ranking.activity_summary.prompt import (
    PROMPT_VERSION,
    RESPONSE_FORMAT,
    SYSTEM_PROMPT,
    MalformedSummaryError,
    normalize_summary,
    summary_text,
    user_message,
)
from products.signals.dags.inbox_ranking.training.telemetry import TrainingEvent

AI_PRODUCT = "activity_summary"
# Not a person: the gateway attributes every call to the pipeline, and the events use the same id.
PIPELINE_DISTINCT_ID = "inbox_ranking_activity_summary"
DEFAULT_MODEL = "gpt-6-luna"
# One retry on a malformed answer. The SDK already retries a failed request on its own.
MAX_ATTEMPTS = 2
REQUEST_TIMEOUT_SECONDS = 120.0

STATUS_OK = "ok"
STATUS_FAILED = "failed"

SUMMARY_GENERATED_EVENT = "activity summary generated"


@frozen
class SummaryPrices:
    input_price_per_million_tokens: float | None
    output_price_per_million_tokens: float | None


def cost_usd(tokens_in: int, tokens_out: int, prices: SummaryPrices) -> float | None:
    """None without both prices, so a run that does not set them records no guess."""
    if prices.input_price_per_million_tokens is None or prices.output_price_per_million_tokens is None:
        return None
    return (
        tokens_in * prices.input_price_per_million_tokens + tokens_out * prices.output_price_per_million_tokens
    ) / 1_000_000


@frozen
class SummaryRequest:
    team_id: int
    user_id: int
    rendered_input: str
    previous_summary: dict[str, Any] | None


@frozen
class SummaryOutcome:
    summary: dict[str, Any] | None
    tokens_in: int
    tokens_out: int
    latency_ms: int
    error: str | None


def gateway_client(partition_key: str) -> OpenAI:
    return build_openai_client(
        "signals",
        ai_product=AI_PRODUCT,
        trace_id=trace_id_from_seed(f"{AI_PRODUCT}:{partition_key}"),
        properties={"partition": partition_key},
        distinct_id=PIPELINE_DISTINCT_ID,
    )


def summarize(client: OpenAI, request: SummaryRequest, *, model: str, as_of: datetime.date) -> SummaryOutcome:
    """One summary. Tokens and latency add up over the attempts, because the retry costs too."""
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message(request.rendered_input, request.previous_summary, as_of)},
    ]
    tokens_in = tokens_out = 0
    error: str | None = None
    started = time.monotonic()
    for _ in range(MAX_ATTEMPTS):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                user=PIPELINE_DISTINCT_ID,
                response_format=RESPONSE_FORMAT,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except OpenAIError as api_error:
            error = f"api_error: {type(api_error).__name__}"
            break
        if response.usage is not None:
            tokens_in += response.usage.prompt_tokens
            tokens_out += response.usage.completion_tokens
        content = response.choices[0].message.content if response.choices else None
        try:
            summary = normalize_summary(content, had_previous_summary=request.previous_summary is not None)
        except MalformedSummaryError as malformed:
            error = f"malformed_output: {malformed}"
            continue
        return SummaryOutcome(
            summary=summary,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=None,
        )
    return SummaryOutcome(
        summary=None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=round((time.monotonic() - started) * 1000),
        error=error,
    )


def summarize_all(
    requests: Sequence[SummaryRequest], summarize_one: Callable[[SummaryRequest], SummaryOutcome], max_concurrency: int
) -> list[SummaryOutcome]:
    """The outcomes in request order, at most `max_concurrency` calls at once."""
    with ThreadPoolExecutor(max_workers=max(1, max_concurrency)) as pool:
        return list(pool.map(summarize_one, requests))


def summary_row(request: SummaryRequest, outcome: SummaryOutcome, *, model: str, prices: SummaryPrices) -> dict:
    return {
        "team_id": request.team_id,
        "user_id": request.user_id,
        "summary_json": json.dumps(outcome.summary, ensure_ascii=False, sort_keys=True) if outcome.summary else None,
        "summary_text": summary_text(outcome.summary) if outcome.summary else None,
        "used_previous_summary": request.previous_summary is not None,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "tokens_in": outcome.tokens_in,
        "tokens_out": outcome.tokens_out,
        "latency_ms": outcome.latency_ms,
        "cost_usd": cost_usd(outcome.tokens_in, outcome.tokens_out, prices),
        "status": STATUS_OK if outcome.summary else STATUS_FAILED,
        "error": outcome.error,
    }


_EVENT_ROW_KEYS = (
    "team_id",
    "user_id",
    "model",
    "prompt_version",
    "status",
    "error",
    "used_previous_summary",
    "tokens_in",
    "tokens_out",
    "cost_usd",
    "latency_ms",
)
_EVENT_INPUT_KEYS = ("n_tasks", "n_mcp_sessions", "n_activity_lines")


def summary_events(
    rows: Sequence[Mapping[str, Any]], inputs: Sequence[Mapping[str, Any]], *, capture_summary_text: bool
) -> list[TrainingEvent]:
    """One event per summary row, `rows[i]` made from `inputs[i]`.

    Counts only by default. The summary text goes on the event only when `capture_summary_text` is
    set, because an event cannot be edited or deleted the way a partition can. The `error` value is
    one of this module's own fixed strings, never model output."""
    events: list[TrainingEvent] = []
    for row, input_row in zip(rows, inputs, strict=True):
        properties: dict[str, object] = {key: row[key] for key in _EVENT_ROW_KEYS}
        properties |= {key: input_row[key] for key in _EVENT_INPUT_KEYS}
        properties |= {f"drops_{rule}": count for rule, count in json.loads(input_row["drops"] or "{}").items()}
        if capture_summary_text and row["summary_json"]:
            summary = json.loads(row["summary_json"])
            properties["summary_text"] = row["summary_text"]
            properties["focus_topics"] = [area["topic"] for area in summary["focus_areas"]]
        events.append(TrainingEvent(event=SUMMARY_GENERATED_EVENT, properties=properties))
    return events
