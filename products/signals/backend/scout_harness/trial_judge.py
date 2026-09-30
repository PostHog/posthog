from __future__ import annotations

import json
from dataclasses import field
from itertools import chain, islice
from typing import TYPE_CHECKING, cast

from openai import RateLimitError, omit
from openai.types.chat import ChatCompletionMessageParam
from pydantic import JsonValue

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.dataclasses import frozen
from posthog.llm.gateway_client import get_async_llm_client, private_scout_gateway
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalScoutRun
from products.signals.backend.rubrics_judging import (
    JUDGE_PROMPT_VERSION as JUDGE_PROMPT_VERSION,
    MAX_JUDGE_INPUT_CHARACTERS as MAX_JUDGE_INPUT_CHARACTERS,
    MAX_JUDGE_OUTPUT_CHARACTERS as MAX_JUDGE_OUTPUT_CHARACTERS,
    TrialJudgeValidationError as TrialJudgeValidationError,
    build_rubric_judge_messages,
    parse_trial_judgment as parse_trial_judgment,
)
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialEvaluationSnapshot,
    TrialEvidenceSource,
    TrialRunEvidence,
    TrialRunJudgment,
)
from products.signals.backend.scout_harness.trial_gateway import create_trial_gateway_token, revoke_trial_gateway_token
from products.signals.backend.scout_harness.trial_launch import assert_trial_environment_ready
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore

if TYPE_CHECKING:
    from collections.abc import Iterator

MAX_TRACE_INPUT_CHARACTERS = 2_000_000
MAX_TRACE_SOURCE_CHARACTERS = 4_000
MAX_TRACE_CHARACTERS = 60_000
MAX_TRACE_SOURCES = 150


@frozen
class TrialTraceEvidence:
    sources: list[TrialEvidenceSource] = field(repr=False)
    limitations: list[str]


def _object(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}


def _tool_content(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _tool_content(item)) is not None]
    if not isinstance(value, dict):
        return value
    if value.get("type") in {"thinking", "reasoning", "redacted_thinking", "analysis"}:
        return None
    return {
        key: _tool_content(item)
        for key, item in value.items()
        if key not in {"_meta", "thinking", "reasoning", "reasoning_content", "reasoning_details", "signature"}
    }


def _render_tool_value(value: JsonValue, path: str) -> Iterator[str]:
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from _render_tool_value(item, f"{path}[{json.dumps(key, ensure_ascii=False)}]")
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _render_tool_value(item, f"{path}[{index}]")
    else:
        # Keep string values literal so quotations do not need a second layer of JSON escaping.
        if isinstance(value, str):
            yield f"{path} (text):\n"
            yield value
        else:
            yield f"{path} (json):\n"
            yield json.dumps(value, ensure_ascii=False, allow_nan=False)
        yield "\n\n"


def evidence_sources_from_logs(
    content: str,
    *,
    max_characters: int = MAX_TRACE_CHARACTERS,
    max_sources: int = MAX_TRACE_SOURCES,
) -> TrialTraceEvidence:
    sources: list[TrialEvidenceSource] = []
    limitations: list[str] = []
    if len(content) > MAX_TRACE_INPUT_CHARACTERS:
        content = content[:MAX_TRACE_INPUT_CHARACTERS].rsplit("\n", 1)[0]
        limitations.append("The session log exceeded the extraction limit; only its beginning was inspected.")
    character_budget = max(0, min(max_characters, MAX_TRACE_CHARACTERS))
    source_limit = max(0, min(max_sources, MAX_TRACE_SOURCES))
    last_payloads: dict[str, str] = {}
    malformed = False
    unsupported = False
    overflow = False
    ignored_updates = {
        "agent_message",
        "agent_message_chunk",
        "agent_thought_chunk",
        "user_message",
        "user_message_chunk",
        "plan",
        "usage_update",
        "current_mode_update",
        "available_commands_update",
        "config_option_update",
        "session_info_update",
    }
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = _object(cast(JsonValue, json.loads(line)))
            notification = _object(entry.get("notification"))
            if notification.get("method") != "session/update":
                if entry.get("type") == "pi_event":
                    unsupported = True
                continue
            update = _object(_object(notification.get("params")).get("update"))
            event = update.get("sessionUpdate")
            if event not in ("tool_call", "tool_call_update", "tool_result"):
                if not isinstance(event, str) or event not in ignored_updates:
                    unsupported = True
                continue
            payload = {
                key: _tool_content(update[key])
                for key in (
                    "sessionUpdate",
                    "toolCallId",
                    "title",
                    "kind",
                    "status",
                    "rawInput",
                    "rawOutput",
                    "content",
                )
                if key in update
            }
            raw_output = _object(payload.get("rawOutput"))
            tool_content = payload.get("content")
            if (
                isinstance(tool_content, list)
                and all(
                    isinstance(item, dict) and set(item) == {"type", "content"} and item["type"] == "content"
                    for item in tool_content
                )
                and json.dumps(
                    [cast(dict[str, JsonValue], item)["content"] for item in tool_content],
                    sort_keys=True,
                    allow_nan=False,
                )
                == json.dumps(raw_output.get("content"), sort_keys=True, allow_nan=False)
            ):
                del payload["content"]
            identity = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            call_id = payload.get("toolCallId")
            if isinstance(call_id, str) and call_id and last_payloads.get(call_id) == identity:
                continue
            blocks = (block for key, value in payload.items() for block in _render_tool_value(value, key))
            # One extra character records truncation without expanding verbose nested field paths.
            text = "".join(islice(chain.from_iterable(blocks), MAX_TRACE_SOURCE_CHARACTERS + 1))
        except (ValueError, TypeError, RecursionError):
            malformed = True
            continue
        if isinstance(call_id, str) and call_id:
            last_payloads[call_id] = identity
        if len(sources) >= source_limit:
            overflow = True
            break
        sources.append(TrialEvidenceSource(id=f"trace:{line_number}", kind="trace", text=text))
    # Reserve space for later results before bounding verbose earlier tool output.
    low, high = 0, MAX_TRACE_SOURCE_CHARACTERS
    while low < high:
        middle = (low + high + 1) // 2
        if sum(min(len(source.text), middle) for source in sources) <= character_budget:
            low = middle
        else:
            high = middle - 1
    truncated = any(len(source.text) > low for source in sources)
    marker = "\n[Tool trace truncated]"
    sources = (
        [
            source.model_copy(
                update={
                    "text": source.text[: low - len(marker)] + marker
                    if len(source.text) > low and low >= len(marker)
                    else source.text[:low]
                }
            )
            for source in sources
        ]
        if low
        else []
    )
    if malformed:
        limitations.append("Some session log entries were malformed and could not be inspected.")
    if unsupported:
        limitations.append("Some session log events use an unsupported format; tool evidence may be incomplete.")
    if truncated:
        limitations.append(
            "Tool trace evidence was truncated to the source or total size limit; omitted actions are unknown."
        )
    if overflow:
        limitations.append("Tool trace evidence was truncated at the source count limit; omitted actions are unknown.")
    if not sources:
        limitations.append("No supported tool-call evidence was available; required tool use cannot be established.")
    return TrialTraceEvidence(sources=sources, limitations=limitations)


def build_trial_judge_messages(
    snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence
) -> list[ChatCompletionMessageParam]:
    return cast(
        list[ChatCompletionMessageParam],
        build_rubric_judge_messages(
            criteria=snapshot.criteria,
            sources=evidence.sources,
            reference_context=snapshot.rubric_reference_context.model_dump(mode="json")
            if snapshot.rubric_reference_context is not None
            else None,
            limitations=evidence.limitations,
            judge_prompt_version=snapshot.judge_prompt_version,
            max_input_characters=MAX_JUDGE_INPUT_CHARACTERS,
        ),
    )


def _create_judge_token(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> str:
    assert_trial_environment_ready()
    if evidence.run_id is None or evidence.task_id is None or evidence.task_run_id is None:
        raise TrialJudgeValidationError("The saved evidence is not bound to a scout task run.")
    if evidence not in snapshot.runs:
        raise TrialJudgeValidationError("The evidence does not belong to this evaluation.")
    run = (
        SignalScoutRun.objects.for_team(snapshot.team_id)
        .select_related("task_run__task")
        .filter(
            id=evidence.run_id,
            scout_config_id=snapshot.config_id,
            task_run_id=evidence.task_run_id,
            task_run__team_id=snapshot.team_id,
            task_run__task_id=evidence.task_id,
            task_run__task__team_id=snapshot.team_id,
            task_run__task__created_by_id=snapshot.user_id,
            task_run__task__deleted=False,
        )
        .first()
    )
    marker = (run.metadata or {}).get("scout_trial") if run is not None else None
    if (
        run is None
        or not isinstance(marker, dict)
        or marker.get("version") != 1
        or marker.get("launch_id") != str(evidence.launch_id)
        or marker.get("context_id") != str(snapshot.context_id)
        or run.task_run.status != "completed"
    ):
        raise TrialJudgeValidationError("The saved scout run is no longer available for this evaluation.")
    if ScoutTrialStore(run).invalid_reason() is not None:
        raise TrialJudgeValidationError("The scout trial was invalidated after its evidence was saved.")
    # Minting also verifies task origin, the task-state marker, and the operator's current project access.
    return create_trial_gateway_token(run)


async def judge_trial_run(snapshot: TrialEvaluationSnapshot, evidence: TrialRunEvidence) -> TrialRunJudgment:
    if evidence.exclusion_reason is not None or evidence.execution_status != "completed":
        return TrialRunJudgment(
            launch_id=evidence.launch_id,
            variant_id=evidence.variant_id,
            status="excluded",
            summary=evidence.exclusion_reason or "The scout run did not complete and cannot be judged for quality.",
        )
    token: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    try:
        with private_capture_context():
            messages = build_trial_judge_messages(snapshot, evidence)
            token = await database_sync_to_async(_create_judge_token, thread_sensitive=False)(snapshot, evidence)
            with private_scout_gateway(token):
                async with get_async_llm_client(product="signals", team_id=snapshot.team_id).with_options(
                    max_retries=0, timeout=240.0 if snapshot.judge_prompt_version == "8" else 120.0
                ) as client:
                    response = await client.chat.completions.create(
                        model=snapshot.judge_model,
                        messages=messages,
                        response_format={"type": "json_object"},
                        max_completion_tokens={"7": 16000, "8": 24000}.get(snapshot.judge_prompt_version, 8000),
                        reasoning_effort="high" if snapshot.judge_prompt_version == "8" else omit,
                        extra_body={"max_retries": 0} if snapshot.judge_prompt_version == "8" else None,
                    )
            if response.usage is not None:
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
            if (
                snapshot.judge_prompt_version in {"7", "8"}
                and response.choices
                and response.choices[0].finish_reason == "length"
            ):
                raise TrialJudgeValidationError(
                    "The judge reached its output token limit before completing the verdict document. "
                    "Review the rubric size before starting a new evaluation; this request was not retried."
                )
            if not response.choices or response.choices[0].finish_reason != "stop":
                raise TrialJudgeValidationError("The judge did not return a complete verdict document.")
            content = response.choices[0].message.content
            if content is None:
                raise TrialJudgeValidationError("The judge did not return a verdict document.")
            verdicts = parse_trial_judgment(
                content,
                criteria=snapshot.criteria,
                sources=evidence.sources,
                judge_prompt_version=snapshot.judge_prompt_version,
            )
        return TrialRunJudgment(
            launch_id=evidence.launch_id,
            variant_id=evidence.variant_id,
            status="judged",
            summary=verdicts.summary,
            criteria=verdicts.criteria,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except TrialJudgeValidationError as error:
        return TrialRunJudgment(
            launch_id=evidence.launch_id,
            variant_id=evidence.variant_id,
            status="judge_error",
            summary="The judge could not produce a reliable evaluation of this run.",
            error=str(error),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except RateLimitError:
        return TrialRunJudgment(
            launch_id=evidence.launch_id,
            variant_id=evidence.variant_id,
            status="judge_error",
            summary="The judge could not evaluate this run. Its quality is unknown.",
            error=(
                "The judge was rate-limited. Wait or check usage limits before starting a new evaluation. "
                "This evaluation will not retry automatically."
            ),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    except Exception:
        return TrialRunJudgment(
            launch_id=evidence.launch_id,
            variant_id=evidence.variant_id,
            status="judge_error",
            summary="The judge could not evaluate this run. Its quality is unknown.",
            error="The private judge request failed. Retry with a new evaluation after checking service availability.",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    finally:
        if token is not None:
            try:
                with private_capture_context():
                    await database_sync_to_async(revoke_trial_gateway_token, thread_sensitive=False)(token)
            except Exception:
                # Do not put provider or database exception details into private evaluation workflow history.
                raise RuntimeError("The private judge credential could not be revoked.") from None
