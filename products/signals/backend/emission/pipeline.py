import json
import asyncio
import dataclasses
from datetime import datetime
from typing import Any

import structlog
import posthoganalytics
from anthropic import AsyncAnthropic
from anthropic.types import MessageParam
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.event_usage import groups
from posthog.llm.gateway_client import get_async_anthropic_gateway_client
from posthog.models import Organization, Team
from posthog.sync import database_sync_to_async

from products.signals.backend.emission.registry import SignalEmitter, SignalEmitterOutput, SignalSourceTableConfig
from products.signals.backend.facade.api import emit_signal

logger = structlog.get_logger(__name__)

LLM_MODEL = "claude-sonnet-4-5"
# Concurrent LLM calls limit for actionability/summarization checks
LLM_CONCURRENCY_LIMIT = 20
# Concurrent workflow spawns for signal emission
EMIT_CONCURRENCY_LIMIT = 50
# Temporal gRPC payload size limit (2 MB)
TEMPORAL_PAYLOAD_MAX_BYTES = 2 * 1024 * 1024
# Maximum number of attempts for LLM calls (summarization & actionability)
LLM_MAX_ATTEMPTS = 3
# Per-call timeout for LLM requests (seconds)
LLM_CALL_TIMEOUT_SECONDS = 120
# Backoff between LLM retry attempts (delay = initial * coefficient ^ (attempt - 1))
LLM_RETRY_INITIAL_DELAY_SECONDS = 5
LLM_RETRY_BACKOFF_COEFFICIENT = 2.0
# Anthropic's Messages API requires max_tokens, so this is a deliberately high safety ceiling
# rather than a tuned budget. The risk we care about is a response being cut off mid-output, not
# runaway generation — the actual outputs here are tiny (a short summary or a one-word verdict).
LLM_MAX_OUTPUT_TOKENS = 8192


def _signals_extra_headers(output: SignalEmitterOutput, stage: str) -> dict[str, str]:
    """Per-call event properties that ride along to the gateway as headers.

    The `team_id` header is set as a default on the client at construction time,
    so it doesn't need to be repeated here. See posthog/llm/gateway_client.py.

    `ai_product` and `$ai_billable` are intentionally NOT set here: the gateway
    derives both from the `signals` product config (the route path sets
    `ai_product=signals` and `billable=True`). Passing them as headers would let a
    typo silently misattribute or mis-bill the generation, so we let the gateway own them.
    """
    return {
        "x-posthog-property-ai_stage": stage,
        "x-posthog-property-source_product": output.source_product,
        "x-posthog-property-source_type": output.source_type,
    }


def _extract_text(response: Any) -> str:
    """Concatenate the text blocks of an Anthropic Messages response (ignores non-text blocks)."""
    return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")


def _capture_pipeline_stage(
    event: str,
    team: Team,
    organization: Organization,
    output: SignalEmitterOutput,
) -> None:
    try:
        posthoganalytics.capture(
            event=event,
            distinct_id=str(team.uuid),
            properties={
                "source_product": output.source_product,
                "source_type": output.source_type,
                "source_id": output.source_id,
            },
            groups=groups(organization, team),
        )
    except Exception:
        # Swallow the exception, to avoid breaking the flow over failed analytics event
        logger.exception(
            "Failed to capture signal pipeline stage event",
            event=event,
            source_product=output.source_product,
            source_type=output.source_type,
            source_id=output.source_id,
        )


def _safe_heartbeat() -> None:
    # Pipeline runs both inside Temporal activities (production) and standalone via the
    # emit_signals_from_fixture management command. Outside an activity context, heartbeat()
    # raises RuntimeError, so we no-op when there's nothing to report to.
    if activity.in_activity():
        activity.heartbeat()


def build_emitter_outputs(
    team_id: int,
    records: list[dict[str, Any]],
    emitter: SignalEmitter,
) -> tuple[list[SignalEmitterOutput], int]:
    outputs = []
    error_count = 0
    for record in records:
        try:
            output = emitter(team_id, record)
        except Exception:
            logger.exception(
                "Emitter failed for record, skipping",
                team_id=team_id,
                record=record,
                signals_type="data-import-signals",
            )
            error_count += 1
            continue
        if output is not None:
            # Avoid serializing datetime objects
            if output.extra:
                output = dataclasses.replace(
                    output,
                    extra={k: v.isoformat() if isinstance(v, datetime) else v for k, v in output.extra.items()},
                )
            outputs.append(output)
    return outputs, error_count


async def _summarize_description(
    client: AsyncAnthropic,
    team_id: int,
    output: SignalEmitterOutput,
    summarization_prompt: str,
    threshold: int,
) -> SignalEmitterOutput:
    messages: list[MessageParam] = [
        {"role": "user", "content": summarization_prompt.format(description=output.description, max_length=threshold)}
    ]
    extra_headers = _signals_extra_headers(output, stage="summarization")
    for attempt in range(LLM_MAX_ATTEMPTS):
        if attempt > 0:
            await asyncio.sleep(LLM_RETRY_INITIAL_DELAY_SECONDS * (LLM_RETRY_BACKOFF_COEFFICIENT ** (attempt - 1)))
        summary = ""
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=LLM_MODEL,
                    messages=messages,
                    max_tokens=LLM_MAX_OUTPUT_TOKENS,
                    metadata={"user_id": f"team-{team_id}"},
                    extra_headers=extra_headers,
                ),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
            summary = _extract_text(response).strip()
            if response.stop_reason == "max_tokens":
                raise ValueError("LLM summary response was truncated due to token limit")
            if not summary:
                raise ValueError("Empty response from LLM when summarizing description")
            if len(summary) > threshold:
                raise ValueError(f"Summary is {len(summary)} characters, must be at most {threshold}")
            return dataclasses.replace(output, description=summary)
        except Exception as e:
            posthoganalytics.capture_exception(
                e,
                properties={
                    "ai_product": "signals",
                    "tag": "signals_import",
                    "error_type": "summarization_failed",
                    "source_type": output.source_type,
                    "source_id": output.source_id,
                    "attempt": attempt + 1,
                },
            )
            # Anthropic requires user/assistant turns to alternate, so only feed the correction
            # back when we actually got assistant text to pair it with; otherwise just retry the
            # existing prompt.
            if summary:
                messages.append({"role": "assistant", "content": summary})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Attempt {attempt + 1} of {LLM_MAX_ATTEMPTS} to summarize description failed with error: {e!r}\nPlease fix your output.",
                    }
                )
    # Hard-truncate the description to the threshold if all attempts failed
    return dataclasses.replace(output, description=output.description[:threshold])


async def summarize_long_descriptions(
    team: Team,
    outputs: list[SignalEmitterOutput],
    summarization_prompt: str,
    threshold: int,
    extra: dict[str, Any],
) -> list[SignalEmitterOutput]:
    needs_summary = [i for i, output in enumerate(outputs) if len(output.description) > threshold]
    if not needs_summary:
        return outputs
    client = get_async_anthropic_gateway_client(product="signals", team_id=team.id)
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY_LIMIT)
    _safe_heartbeat()
    completed_count = 0

    async def _bounded_summarize(output: SignalEmitterOutput) -> SignalEmitterOutput | None:
        nonlocal completed_count
        async with semaphore:
            try:
                result = await _summarize_description(client, team.id, output, summarization_prompt, threshold)
            except Exception:
                logger.exception(
                    "Summarization failed, skipping signal",
                    signal_source_id=output.source_id,
                    **extra,
                )
                return None
            finally:
                completed_count += 1
                if completed_count % LLM_CONCURRENCY_LIMIT == 0:
                    _safe_heartbeat()
            return result

    tasks: dict[int, asyncio.Task[SignalEmitterOutput | None]] = {}
    async with asyncio.TaskGroup() as tg:
        for i in needs_summary:
            tasks[i] = tg.create_task(_bounded_summarize(outputs[i]))
    result: list[SignalEmitterOutput] = []
    skipped = 0
    for i, output in enumerate(outputs):
        if i not in tasks:
            result.append(output)
        elif (summarized := tasks[i].result()) is not None:
            result.append(summarized)
        else:
            skipped += 1
    logger.info(
        f"Summarized {len(needs_summary) - skipped} long descriptions, skipped {skipped} (threshold={threshold})",
        signals_type="data-import-signals",
        **extra,
    )
    return result


async def _check_actionability(
    client: AsyncAnthropic,
    team_id: int,
    output: SignalEmitterOutput,
    actionability_prompt: str,
) -> bool:
    prompt = actionability_prompt.format(description=output.description)
    extra_headers = _signals_extra_headers(output, stage="actionability")
    for attempt in range(LLM_MAX_ATTEMPTS):
        if attempt > 0:
            await asyncio.sleep(LLM_RETRY_INITIAL_DELAY_SECONDS * (LLM_RETRY_BACKOFF_COEFFICIENT ** (attempt - 1)))
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=LLM_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=LLM_MAX_OUTPUT_TOKENS,
                    metadata={"user_id": f"team-{team_id}"},
                    extra_headers=extra_headers,
                ),
                timeout=LLM_CALL_TIMEOUT_SECONDS,
            )
            response_text = _extract_text(response).strip().upper()
            return "NOT_ACTION" not in response_text
        except Exception as e:
            posthoganalytics.capture_exception(
                e,
                properties={
                    "ai_product": "signals",
                    "tag": "signals_import",
                    "error_type": "actionability_check_failed",
                    "source_type": output.source_type,
                    "source_id": output.source_id,
                    "attempt": attempt + 1,
                },
            )
    # Assume actionable if all retries exhausted
    return True


async def filter_actionable(
    team: Team,
    outputs: list[SignalEmitterOutput],
    actionability_prompt: str,
    extra: dict[str, Any],
) -> list[SignalEmitterOutput]:
    client = get_async_anthropic_gateway_client(product="signals", team_id=team.id)
    semaphore = asyncio.Semaphore(LLM_CONCURRENCY_LIMIT)
    _safe_heartbeat()
    checked_count = 0

    async def _bounded_check(output: SignalEmitterOutput) -> bool:
        nonlocal checked_count
        async with semaphore:
            try:
                result = await _check_actionability(client, team.id, output, actionability_prompt)
            except Exception:
                logger.exception(
                    "Actionability check failed, assuming actionable",
                    signal_source_id=output.source_id,
                    **extra,
                )
                return True
            finally:
                checked_count += 1
                if checked_count % LLM_CONCURRENCY_LIMIT == 0:
                    _safe_heartbeat()
            return result

    tasks: dict[int, asyncio.Task[bool]] = {}
    async with asyncio.TaskGroup() as tg:
        for i, output in enumerate(outputs):
            tasks[i] = tg.create_task(_bounded_check(output))
    actionable = []
    filtered_count = 0
    for i, output in enumerate(outputs):
        if tasks[i].result():
            actionable.append(output)
        else:
            filtered_count += 1
            logger.info(
                "Filtered non-actionable signal",
                signal_source_type=output.source_type,
                signal_source_id=output.source_id,
                **extra,
            )
    if filtered_count > 0:
        logger.info(
            f"Filtered {filtered_count} non-actionable records out of {len(outputs)}",
            signals_type="data-import-signals",
            **extra,
        )
    return actionable


def _estimate_output_payload_bytes(output: SignalEmitterOutput) -> int:
    return len(
        json.dumps(
            {
                "source_type": output.source_type,
                "source_id": output.source_id,
                "description": output.description,
                "weight": output.weight,
                "extra": output.extra,
            },
        ).encode("utf-8")
    )


async def _emit_signals(
    team: Team,
    outputs: list[SignalEmitterOutput],
    extra: dict[str, Any],
) -> int:
    semaphore = asyncio.Semaphore(EMIT_CONCURRENCY_LIMIT)
    _safe_heartbeat()
    completed_count = 0

    async def _bounded_emit(output: SignalEmitterOutput) -> bool:
        nonlocal completed_count
        async with semaphore:
            try:
                payload_bytes = _estimate_output_payload_bytes(output)
                if payload_bytes > TEMPORAL_PAYLOAD_MAX_BYTES:
                    without_extra = dataclasses.replace(output, extra={})
                    if _estimate_output_payload_bytes(without_extra) > TEMPORAL_PAYLOAD_MAX_BYTES:
                        msg = "Signal payload exceeds Temporal limit even without extra metadata"
                        logger.error(
                            msg,
                            signal_source_type=output.source_type,
                            signal_source_id=output.source_id,
                            **extra,
                        )
                        raise ValueError(msg)
                    logger.error(
                        f"Signal extra metadata too large ({payload_bytes} bytes), emitting without extra",
                        signal_source_type=output.source_type,
                        signal_source_id=output.source_id,
                        **extra,
                    )
                    output = without_extra
                await emit_signal(
                    team=team,
                    source_product=output.source_product,
                    source_type=output.source_type,
                    source_id=output.source_id,
                    description=output.description,
                    weight=output.weight,
                    extra=output.extra,
                )
                return True
            except Exception as e:
                logger.exception(f"Error emitting signal for record: {e}", **extra)
                return False
            finally:
                completed_count += 1
                if completed_count % EMIT_CONCURRENCY_LIMIT == 0:
                    _safe_heartbeat()

    results: dict[int, asyncio.Task[bool]] = {}
    async with asyncio.TaskGroup() as tg:
        for i, output in enumerate(outputs):
            results[i] = tg.create_task(_bounded_emit(output))
    succeeded = sum(1 for task in results.values() if task.result())
    if succeeded == 0 and len(outputs) > 0:
        raise RuntimeError(f"All {len(outputs)} signal emissions failed")
    return succeeded


async def run_signal_pipeline(
    team: Team,
    config: SignalSourceTableConfig,
    records: list[dict[str, Any]],
    extra: dict[str, Any],
) -> dict[str, Any]:
    source_label = f"{config.source_product}/{config.source_type}"

    if not records:
        logger.warning(f"No new records found for {source_label}", **extra)
        return {"status": "success", "reason": "no_new_records", "signals_emitted": 0}

    outputs, error_count = build_emitter_outputs(
        team_id=team.id,
        records=records,
        emitter=config.emitter,
    )
    # Only fail if every record raised — emitters may return None as a benign skip,
    # so a mix of skips and errors should fall through to the no_actionable_records path.
    if error_count == len(records):
        raise ApplicationError(
            f"All {len(records)} records failed emitter for {source_label}",
            non_retryable=True,
        )
    logger.info(f"Built {len(outputs)} signal outputs from {len(records)} records for {source_label}", **extra)

    organization = await database_sync_to_async(lambda: team.organization)()
    for output in outputs:
        _capture_pipeline_stage("signal_data_source_entered", team, organization, output)

    if config.summarization_prompt is not None and config.description_summarization_threshold_chars is not None:
        threshold = config.description_summarization_threshold_chars
        pre_summary_by_id = {o.source_id: o for o in outputs}
        outputs = await summarize_long_descriptions(
            team=team,
            outputs=outputs,
            summarization_prompt=config.summarization_prompt,
            threshold=threshold,
            extra=extra,
        )
        for output in outputs:
            pre = pre_summary_by_id.get(output.source_id)
            if pre is not None and len(pre.description) > threshold:
                _capture_pipeline_stage("signal_data_source_summarized", team, organization, output)

    if config.actionability_prompt:
        pre_filter_by_id = {o.source_id: o for o in outputs}
        outputs = await filter_actionable(
            team=team,
            outputs=outputs,
            actionability_prompt=config.actionability_prompt,
            extra=extra,
        )
        post_filter_ids = {o.source_id for o in outputs}
        for source_id, output in pre_filter_by_id.items():
            if source_id not in post_filter_ids:
                _capture_pipeline_stage("signal_data_source_filtered", team, organization, output)

    if not outputs:
        logger.warning(f"No actionable records after filtering for {source_label}", **extra)
        return {"status": "success", "reason": "no_actionable_records", "signals_emitted": 0}

    signals_emitted = await _emit_signals(
        team=team,
        outputs=outputs,
        extra=extra,
    )
    logger.info(f"Emitted {signals_emitted} signals for {source_label}", **extra)
    return {"status": "success", "signals_emitted": signals_emitted}
