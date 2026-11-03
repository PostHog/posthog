"""Emit sandboxed eval trace events ($ai_generation, $ai_span, $ai_trace) to PostHog.

Consumes a ``ParsedLog`` produced by ``acp_log.parse_log`` plus scoring
results from Braintrust. Owns the constants shared with scorer tracing
(``DISTINCT_ID``) so they live alongside their primary consumer.
"""

from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime
from typing import Any

from posthoganalytics import Posthog

from .acp_log import GenerationDescriptor, ParsedLog, SpanDescriptor
from .log_parser import describe_tool_use

logger = logging.getLogger(__name__)

type RunMetadata = dict[str, str | int | bool | None]

DISTINCT_ID = "llma_eval"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_PROVIDER = "anthropic"
_RUNTIME_PROVIDERS = {"codex": "openai"}
TOOL_STATE_CHAR_LIMIT = 2_000


def _parse_iso_timestamp(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


class TraceEventEmitter:
    """Emits PostHog $ai_* events for a single eval case trace.

    Holds the PostHog client, trace_id, and experiment metadata so individual
    emit methods don't have to thread them through every call.
    """

    def __init__(
        self,
        client: Posthog,
        trace_id: str,
        experiment_id: str,
        experiment_name: str,
        case_name: str,
        namespace: str,
        *,
        run_metadata: RunMetadata,
    ):
        self._client = client
        self._trace_id = trace_id
        self._experiment_id = experiment_id
        self._formatted_experiment_name = f"{namespace}/{experiment_name}"
        self._case_name = case_name
        self._run_metadata = run_metadata

    @property
    def _eval_metadata(self) -> dict[str, Any]:
        return {
            **self._run_metadata,
            "ai_product": "evals",
            "$ai_experiment_id": self._experiment_id,
            "$ai_experiment_name": self._formatted_experiment_name,
        }

    def emit_parsed_events(self, parsed: ParsedLog) -> None:
        """Emit ``$ai_generation`` per model turn and ``$ai_span`` per log span."""
        error_spans = [s for s in parsed.spans if s.span_name == "error"]
        model = parsed.model or DEFAULT_MODEL

        tool_results = _tool_results(parsed)
        tool_spans = 0
        for gen in parsed.generations:
            generation_span_id = self._emit_generation(gen, error_spans, model)
            for block in gen.output_content:
                if block.get("type") == "tool_use":
                    self._emit_tool_span(block, tool_results, parsed, generation_span_id)
                    tool_spans += 1
        for span in parsed.spans:
            self._emit_span(span)

        # NOTE: $ai_trace root event is emitted separately by emit_trace_root()
        # after scoring completes, so it can include scores in the output.

        logger.info(
            "Emitted child events for '%s' (trace=%s): %d generations, %d tool spans, %d spans",
            self._case_name,
            self._trace_id,
            len(parsed.generations),
            tool_spans,
            len(parsed.spans),
        )

    @property
    def _provider(self) -> str:
        runtime = self._run_metadata.get("agent_runtime")
        return _RUNTIME_PROVIDERS.get(runtime, DEFAULT_PROVIDER) if isinstance(runtime, str) else DEFAULT_PROVIDER

    def _emit_generation(self, gen: GenerationDescriptor, error_spans: list[SpanDescriptor], model: str) -> str:
        # Prefer the real "model call invoked" time; fall back to first-output time.
        gen_start = _parse_iso_timestamp(gen.start_ts) or _parse_iso_timestamp(gen.timestamp)
        gen_end = _parse_iso_timestamp(gen.end_ts) or _parse_iso_timestamp(gen.timestamp)

        span_id = str(uuid.uuid4())
        properties: dict[str, Any] = {
            **self._eval_metadata,
            "$ai_trace_id": self._trace_id,
            "$ai_span_id": span_id,
            "$ai_parent_id": self._trace_id,
            "$ai_model": model,
            "$ai_provider": self._provider,
            "$ai_input": gen.input_messages,
        }
        if gen.output_content:
            properties["$ai_output_choices"] = [
                {"role": "assistant", "content": gen.output_content},
            ]

        # Token usage. The ACP agent-server emits one ``usage`` block per session
        # (at end_turn), so only the final generation carries non-empty counts when
        # a session spans multiple model calls.
        self._apply_token_usage(properties, gen.token_usage)

        if gen_start and gen_end and gen_end >= gen_start:
            properties["$ai_latency"] = (gen_end - gen_start).total_seconds()

        self._apply_matching_errors(properties, error_spans, gen_start, gen_end)

        capture_kwargs: dict[str, Any] = {}
        if gen_start:
            capture_kwargs["timestamp"] = gen_start

        self._client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_generation",
            properties=properties,
            **capture_kwargs,
        )
        return span_id

    def _emit_tool_span(
        self,
        tool_use: dict[str, Any],
        tool_results: dict[str, dict[str, Any]],
        parsed: ParsedLog,
        generation_span_id: str,
    ) -> None:
        """One ``$ai_span`` per tool call, the shape production MCP analytics emits from ``trackToolSpan``."""
        call_id = str(tool_use.get("id") or "")
        raw_name = str(tool_use.get("name") or "")
        tool_input = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
        name, inner_input = describe_tool_use(raw_name, tool_input)
        result = tool_results.get(call_id)
        timing = parsed.tool_timings.get(call_id)
        started = _parse_iso_timestamp(timing.started_at) if timing else None
        ended = _parse_iso_timestamp(timing.ended_at) if timing else None

        properties: dict[str, Any] = {
            **self._eval_metadata,
            "$ai_trace_id": self._trace_id,
            "$ai_span_id": str(uuid.uuid4()),
            "$ai_parent_id": generation_span_id,
            "$ai_span_name": name,
            "$ai_input_state": _truncate(json.dumps(inner_input, default=str)),
            # A call with no result never finished, which reads as a failure everywhere else in the harness.
            "$ai_is_error": result is None or bool(result.get("is_error")),
            "tool_raw_name": raw_name,
        }
        if result is not None:
            properties["$ai_output_state"] = _truncate(str(result.get("content") or ""))
        if timing is not None:
            properties["tool_sequence"] = timing.sequence
        if started and ended and ended >= started:
            properties["$ai_latency"] = (ended - started).total_seconds()

        capture_kwargs: dict[str, Any] = {"timestamp": started} if started else {}
        self._client.capture(distinct_id=DISTINCT_ID, event="$ai_span", properties=properties, **capture_kwargs)

    @staticmethod
    def _apply_token_usage(properties: dict[str, Any], token_usage: dict[str, int]) -> None:
        if not token_usage:
            return
        if "inputTokens" in token_usage:
            properties["$ai_input_tokens"] = token_usage["inputTokens"]
        if "outputTokens" in token_usage:
            properties["$ai_output_tokens"] = token_usage["outputTokens"]
        if token_usage.get("cachedReadTokens"):
            properties["$ai_cache_read_input_tokens"] = token_usage["cachedReadTokens"]
        if token_usage.get("cachedWriteTokens"):
            properties["$ai_cache_creation_input_tokens"] = token_usage["cachedWriteTokens"]

    @staticmethod
    def _apply_matching_errors(
        properties: dict[str, Any],
        error_spans: list[SpanDescriptor],
        gen_start: datetime | None,
        gen_end: datetime | None,
    ) -> None:
        """Attribute errors that fired within this generation's time window."""
        if not gen_start:
            return
        matching: list[str] = []
        for span in error_spans:
            span_ts = _parse_iso_timestamp(span.timestamp)
            if not span_ts:
                continue
            if span_ts >= gen_start and (gen_end is None or span_ts <= gen_end):
                matching.append(span.content or "unknown error")
        if matching:
            properties["$ai_is_error"] = True
            properties["$ai_error"] = "; ".join(matching)[:2000]

    def _emit_span(self, span: SpanDescriptor) -> None:
        capture_kwargs: dict[str, Any] = {}
        span_ts = _parse_iso_timestamp(span.timestamp)
        if span_ts:
            capture_kwargs["timestamp"] = span_ts

        self._client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_span",
            properties={
                **self._eval_metadata,
                "$ai_trace_id": self._trace_id,
                "$ai_span_id": span.span_id,
                "$ai_parent_id": self._trace_id,
                "$ai_span_name": span.span_name,
                "$ai_output_state": span.content,
            },
            **capture_kwargs,
        )

    def emit_root(
        self,
        prompt: str,
        duration: float,
        first_timestamp: str,
        last_message: str = "",
        artifacts_summary: dict[str, Any] | None = None,
        scores: dict[str, float | None] | None = None,
        token_usage: dict[str, int] | None = None,
    ) -> None:
        """Emit the ``$ai_trace`` root event after scoring so output includes scores.

        Token usage is placed here (not on individual generations) because the ACP
        log only reports aggregate totals at ``end_turn``, not per sub-generation.
        """
        prompt_preview = prompt[:20].replace("\n", " ") if prompt else ""
        trace_name = f"{self._case_name}: {prompt_preview}" if prompt_preview else self._case_name

        output_state: dict[str, Any] = {}
        if last_message:
            output_state["last_message"] = last_message
        if scores:
            output_state["scores"] = scores
        if artifacts_summary:
            output_state["artifacts"] = artifacts_summary

        properties: dict[str, Any] = {
            **self._eval_metadata,
            "$ai_trace_id": self._trace_id,
            "$ai_trace_name": trace_name,
            "$ai_latency": duration,
        }
        if prompt:
            properties["$ai_input_state"] = {"prompt": prompt}
        if output_state:
            properties["$ai_output_state"] = output_state
        if token_usage:
            properties["$ai_input_tokens"] = token_usage.get("inputTokens", 0)
            properties["$ai_output_tokens"] = token_usage.get("outputTokens", 0)
            properties["$ai_cache_read_input_tokens"] = token_usage.get("cachedReadTokens", 0)

        capture_kwargs: dict[str, Any] = {}
        ts = _parse_iso_timestamp(first_timestamp)
        if ts:
            capture_kwargs["timestamp"] = ts

        self._client.capture(
            distinct_id=DISTINCT_ID,
            event="$ai_trace",
            properties=properties,
            **capture_kwargs,
        )


def _tool_results(parsed: ParsedLog) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for message in parsed.messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                results[str(block["tool_use_id"])] = block
    return results


def _truncate(text: str) -> str:
    return text if len(text) <= TOOL_STATE_CHAR_LIMIT else text[:TOOL_STATE_CHAR_LIMIT] + "…"


def emit_trace_events(
    client: Posthog,
    trace_id: str,
    experiment_id: str,
    experiment_name: str,
    case_name: str,
    parsed: ParsedLog,
    *,
    namespace: str,
    run_metadata: RunMetadata,
) -> None:
    """Emit one ``$ai_generation`` per turn, plus ``$ai_span`` events.

    Thin wrapper over ``TraceEventEmitter.emit_parsed_events``.
    """
    TraceEventEmitter(
        client, trace_id, experiment_id, experiment_name, case_name, namespace, run_metadata=run_metadata
    ).emit_parsed_events(parsed)


def emit_trace_root(
    client: Posthog,
    trace_id: str,
    experiment_id: str,
    experiment_name: str,
    case_name: str,
    *,
    namespace: str,
    run_metadata: RunMetadata,
    prompt: str,
    duration: float,
    first_timestamp: str,
    last_message: str = "",
    artifacts_summary: dict[str, Any] | None = None,
    scores: dict[str, float | None] | None = None,
    token_usage: dict[str, int] | None = None,
) -> None:
    """Thin wrapper over ``TraceEventEmitter.emit_root``."""
    TraceEventEmitter(
        client, trace_id, experiment_id, experiment_name, case_name, namespace, run_metadata=run_metadata
    ).emit_root(
        prompt=prompt,
        duration=duration,
        first_timestamp=first_timestamp,
        last_message=last_message,
        artifacts_summary=artifacts_summary,
        scores=scores,
        token_usage=token_usage,
    )
