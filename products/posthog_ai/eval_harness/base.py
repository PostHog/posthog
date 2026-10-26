from __future__ import annotations

import os
import time
import uuid
import asyncio
import hashlib
import logging
import traceback
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from django.db import (
    OperationalError as DjangoOperationalError,
    close_old_connections,
)

import orjson
from botocore.exceptions import ClientError, ConnectionClosedError, EndpointConnectionError, ReadTimeoutError
from clickhouse_driver.errors import ErrorCodes, NetworkError, ServerException, SocketTimeoutError
from psycopg import OperationalError as PsycopgOperationalError

from posthog.dataclasses import frozen
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryMemoryLimitExceeded, ClickHouseQueryTimeOut

from products.posthog_ai.backend.services.system_prompt.service import PromptService
from products.tasks.backend.facade.agents import EVAL_INTERACTION_ORIGIN, CustomPromptSandboxContext, TurnPollTimeout

from .acp_log import ParsedLog, parse_log
from .config import AgentArtifacts, BaseEvalCase, SandboxedEvalCase
from .engines.base import EvalEngine
from .engines.types import CaseHooks, CaseSpec, ExperimentResult, ExperimentSpec, SpanKind
from .harness.kernel_sandboxes import reclaim_kernels
from .harness.reporting import CasePhase
from .harness.retries import infrastructure_retry_delay
from .harness.trial_stats import trial_stats
from .log_parser import describe_tool_use
from .log_sink import append_case_scores, build_case_dir, write_case_logs
from .offline_results import OfflineEvalPublisher, OfflineEvalSettings, OfflineEvalSuite, OfflineUploadError
from .runner import AgentNeverRanError, EvalCaseResult, agent_never_ran, run_eval_case
from .scorers import ExitCodeZero, wrap_scorers
from .trace_events import RunMetadata, emit_trace_events, emit_trace_root

if TYPE_CHECKING:
    from .harness.context import EvalContext

logger = logging.getLogger(__name__)


def _get_last_assistant_text(parsed: ParsedLog) -> str:
    """Extract the last assistant message text from the final generation."""
    for gen in reversed(parsed.generations):
        if not gen.output_content:
            continue
        texts = [b.get("text", "") for b in gen.output_content if isinstance(b, dict) and b.get("type") == "text"]
        text = "\n".join(t for t in texts if t)
        if text:
            return text
    return ""


def _log_conversation_spans(hooks: CaseHooks, parsed: ParsedLog) -> None:
    """Log each conversation message as a child span so Braintrust renders a trace tree.

    Uses the same Anthropic-format messages as PostHog trace capture.
    """
    for msg in parsed.messages:
        role = msg.get("role", "system")
        content = msg.get("content", "")

        # Anthropic format: content can be a string or list of content blocks
        tool_calls: list[dict[str, Any]] = []
        if isinstance(content, list):
            # Render content blocks for display
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    parts.append(block.get("text", ""))
                elif block_type == "tool_use":
                    block_input = block.get("input")
                    tool, tool_input = describe_tool_use(
                        block.get("name"), block_input if isinstance(block_input, dict) else {}
                    )
                    tool_calls.append({"tool": tool, "input": tool_input})
                    parts.append(f"[tool_use: {tool or '?'}]")
                elif block_type == "tool_result":
                    result_text = str(block.get("content", ""))[:500]
                    is_error = block.get("is_error", False)
                    prefix = "[tool_result error]" if is_error else "[tool_result]"
                    parts.append(f"{prefix} {result_text}")
            display_content = "\n".join(parts)
        else:
            display_content = str(content)

        if role == "assistant" and tool_calls:
            for tool_call in tool_calls:
                with hooks.start_span(f"tool_call: {tool_call['tool']}", "function") as span:
                    span.log(input=[tool_call], output=display_content)
            continue

        span_type: SpanKind
        if role == "assistant":
            span_type = "function" if tool_calls else "llm"
            # Naming the span after the resolved tool keeps the trace tree scannable;
            # every single-exec call would otherwise read as an undifferentiated "exec".
            if len(tool_calls) == 1:
                name = f"tool_call: {tool_calls[0]['tool']}"
            else:
                name = "tool_call" if tool_calls else "agent"
        elif role == "user":
            has_tool_result = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )
            span_type = "function"
            name = "tool_result" if has_tool_result else "user"
        else:
            span_type = "function"
            name = role

        with hooks.start_span(name, span_type) as span:
            if role == "user":
                span.log(input=display_content)
            elif role == "assistant":
                # Logged untruncated: the arguments are the only record of what the
                # agent asked for, and a query payload is easy to cut short.
                if tool_calls:
                    span.log(input=tool_calls, output=display_content)
                else:
                    span.log(output=display_content)
            else:
                span.log(metadata={"message": display_content})

    # Also log non-AI spans (console, errors)
    for span_desc in parsed.spans:
        with hooks.start_span(span_desc.span_name, "function") as span:
            span.log(metadata={"message": span_desc.content})


class _BaseEvalRun:
    """One evaluation suite run — the per-experiment state and the generic
    Braintrust orchestration, independent of how a case's task executes.

    Holds the experiment id, the case lookups, the local log dir, and the scorer
    wiring so the Braintrust ``_task`` and the post-scoring ``_finalize`` share
    them without a giant closure. Subclasses implement ``_execute_case`` (the
    per-case work) and ``_timeout_output`` (the scored-0 shape for a case that
    outran its budget); ``_SandboxedEvalRun`` is the sandbox-agent incarnation.
    """

    trace_namespace = "evals"
    """Experiment-name prefix on PostHog trace events. Subclasses set it per run kind."""

    def __init__(
        self,
        experiment_name: str,
        cases: Sequence[BaseEvalCase],
        scorers: Sequence[Any],
        ctx: EvalContext,
        is_public: bool,
        no_send_logs: bool,
        engine: EvalEngine | None = None,
        offline_suite: OfflineEvalSuite | None = None,
        send_to_posthog: bool | None = None,
    ) -> None:
        self.experiment_name = experiment_name
        self.cases = cases
        self.ctx = ctx
        self.is_public = is_public
        self.no_send_logs = no_send_logs
        self.send_to_posthog = not no_send_logs if send_to_posthog is None else send_to_posthog
        self.offline_suite = offline_suite
        self.offline_publisher: OfflineEvalPublisher | None = None
        self.started_at = datetime.now(UTC)
        # The execution/reporting backend, resolved once per run and shared via
        # ctx.engine; an explicit engine (in tests) overrides it.
        self.engine = engine or ctx.engine

        # Generate a unique experiment ID per eval run
        self.experiment_id = str(uuid.uuid4())

        self.posthog_client = ctx.posthog_client

        # Shared lookups populated by _task(), read after the experiment run completes.
        self.agent_trace_id_lookup: dict[str, str] = {}
        # Per-case metadata for emitting $ai_trace root events after scoring.
        self.case_trace_meta: dict[str, dict[str, Any]] = {}
        self._trial_counts: dict[str, int] = {}

        # Local disk sink for raw agent logs — lets an agent iterating on the
        # harness read back what happened without round-tripping through Braintrust.
        self.run_log_dir = build_case_dir(experiment_name, self.experiment_id)

        # Wrap scorers with tracing if PostHog client is available
        self.scorer_traces: dict[tuple[str, str], str] = {}
        if self.posthog_client:
            self.active_scorers, self.scorer_traces = wrap_scorers(
                scorers,
                self.posthog_client,
                self.experiment_id,
                experiment_name,
                self.agent_trace_id_lookup,
                trace_namespace=self.trace_namespace,
                run_metadata=self._experiment_metadata(),
            )
        else:
            self.active_scorers = list(scorers)

        self.case_filter = ctx.case_filter

        # Instance-scoped lookup so callable hooks on a case (e.g. a sandboxed
        # case's `setup`) can be re-bound inside `_task()` — they don't survive
        # Braintrust's JSON round-trip, but the original case objects do.
        self.cases_by_name: dict[str, BaseEvalCase] = {c.name: c for c in cases}

    def _case_input(self, case: BaseEvalCase) -> dict[str, Any]:
        """The JSON-safe ``input`` dict a case round-trips through Braintrust as."""
        return {"name": case.name, "prompt": case.prompt, "followups": case.followups}

    def _build_eval_cases(self) -> list[CaseSpec]:
        eval_cases: list[CaseSpec] = []
        for case in self.cases:
            if self.case_filter and self.case_filter not in case.name:
                continue
            eval_cases.append(CaseSpec(input=self._case_input(case), expected=case.expected, metadata=case.metadata))
        return eval_cases

    async def _execute_case(self, input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        """Run one case and return the scorer ``output`` dict.

        Owns the case's concurrency slot and its ``asyncio.wait_for`` budget;
        a ``TimeoutError`` escaping here is scored 0 by ``_task`` rather than
        marked as an infra error.
        """
        raise NotImplementedError

    def _timeout_output(self) -> dict[str, Any]:
        """The scorer ``output`` dict for a case that outran its budget."""
        raise NotImplementedError

    def _project_name(self) -> str:
        return self.experiment_name

    def _experiment_metadata(self) -> RunMetadata:
        """The run's configuration, sent to the engine and stamped on every PostHog event."""
        metadata: RunMetadata = {
            "agent_model": self.ctx.agent_model,
            "trials": self.ctx.trials,
            "git_sha": self.ctx.git_sha,
            "git_dirty": self.ctx.git_dirty,
        }
        if self.ctx.skills_sha256 is not None:
            metadata["skills_sha256"] = self.ctx.skills_sha256
        if self.ctx.skills_source_sha256 is not None:
            metadata["skills_source_sha256"] = self.ctx.skills_source_sha256
        return metadata

    async def _task(self, input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any] | None:
        case_started = time.monotonic()
        case_name = input.get("name", "?")
        hooks.metadata["trial_id"] = str(uuid.uuid4())
        hooks.metadata["trial_index"] = self._trial_counts.get(case_name, 0)
        self._trial_counts[case_name] = hooks.metadata["trial_index"] + 1
        hooks.metadata["phase_durations"] = await self.ctx.reporter.case_started(
            self.experiment_name, case_name, hooks.metadata["trial_id"], hooks.metadata["trial_index"]
        )
        status: Literal["ok", "timeout", "error"] = "ok"
        error_type: str | None = None
        error_detail: str | None = None
        cancelled = False
        try:
            return await self._execute_case(input, hooks)
        except (TimeoutError, TurnPollTimeout) as error:
            # A case that outran its budget is a task result (too slow), not an
            # infra error: score it 0 rather than letting Braintrust mark it errored.
            status = "timeout"
            output = self._timeout_output()
            if isinstance(error, TurnPollTimeout):
                hooks.metadata["poll_timeout"] = error.diagnostics()
                output["stderr"] = str(error)
            if poll_timeout := hooks.metadata.get("poll_timeout"):
                output["poll_timeout"] = poll_timeout
            error_detail = str(output.get("stderr") or output.get("error") or "")
            logger.warning("Eval case '%s' timed out: %s", case_name, error_detail)
            try:
                write_case_logs(
                    case_dir=self.run_log_dir,
                    case_name=case_name,
                    raw_log="",
                    artifacts=output,
                    prompt=input.get("prompt", ""),
                    duration=time.monotonic() - case_started,
                    last_message=str(output.get("stderr") or output.get("error") or "Case timed out"),
                    trial_id=hooks.metadata["trial_id"],
                )
            except Exception:
                logger.exception("Failed to write timeout logs for '%s'", case_name)
            return output
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as error:
            error_type = type(error).__name__
            error_detail = "".join(traceback.format_exception(error)).rstrip()
            # Infra failure (provisioning, demo copy, setup hook, poll). Re-raise so
            # Braintrust records the case as errored and excludes it from score
            # averages, instead of scoring the task 0 for the harness's fault.
            status = "error"
            logger.exception("Eval task errored for '%s'", case_name)
            raise
        finally:
            # Report on every path so the reporter's live case counter never stalls.
            if cancelled:
                await self.ctx.reporter.finish_cases([hooks.metadata["trial_id"]])
            else:
                await self.ctx.reporter.case_done(
                    self.experiment_name,
                    case_name,
                    duration_seconds=time.monotonic() - case_started,
                    status=status,
                    trial_id=hooks.metadata["trial_id"],
                    error_type=error_type,
                    error_detail=error_detail,
                )

    async def _set_case_phase(self, hooks: CaseHooks | None, phase: CasePhase) -> None:
        if hooks is not None and (trial_id := hooks.metadata.get("trial_id")):
            await self.ctx.reporter.case_phase(trial_id, phase)

    async def _finalize(self, result: ExperimentResult) -> None:
        """Append scores to local summaries, emit PostHog trace-root
        events, and hand the summary to the reporter — after scoring completes."""
        # Append final scores to local summary files for every case we wrote.
        if result.results:
            for eval_result in result.results:
                case_name = eval_result.input.get("name", "") if isinstance(eval_result.input, dict) else ""
                if not case_name:
                    continue
                try:
                    append_case_scores(
                        self.run_log_dir,
                        case_name,
                        dict(eval_result.scores or {}),
                        trial_id=eval_result.metadata.get("trial_id"),
                        phase_durations=eval_result.metadata.get("phase_durations"),
                    )
                except Exception:
                    logger.exception("Failed to append scores to local log summary for '%s'", case_name)

        # Emit trace roots to PostHog (after scoring)
        if self.posthog_client and result.results:
            try:
                # Emit $ai_trace root events now that scores are available
                for eval_result in result.results:
                    case_name = eval_result.input.get("name", "") if isinstance(eval_result.input, dict) else ""
                    trial_id = str(eval_result.metadata.get("trial_id") or case_name)
                    trace_id = self.agent_trace_id_lookup.get(trial_id)
                    meta = self.case_trace_meta.get(trial_id)
                    if trace_id and meta:
                        emit_trace_root(
                            self.posthog_client,
                            trace_id=trace_id,
                            experiment_id=self.experiment_id,
                            experiment_name=self.experiment_name,
                            case_name=case_name,
                            namespace=self.trace_namespace,
                            prompt=meta["prompt"],
                            duration=meta["duration"],
                            first_timestamp=meta["first_timestamp"],
                            last_message=meta.get("last_message", ""),
                            artifacts_summary=meta.get("artifacts_summary"),
                            scores=eval_result.scores,
                            token_usage=meta.get("token_usage"),
                            run_metadata=self._experiment_metadata(),
                        )
                await asyncio.to_thread(self.posthog_client.flush)
            except Exception:
                logger.exception("Failed to emit trace roots for '%s'", self.experiment_name)

        # Hand the summary to the reporter: suites don't return their Braintrust
        # result up to the orchestrator, so this is the only place the final table
        # and the EXPORT_EVAL_RESULTS jsonl can read per-scorer scores from.
        # Errored cases (infra failures) are surfaced separately so they read as noise,
        # not as agent 0s dragging the averages.
        error_count = sum(1 for r in result.results if r.error is not None)
        await self.ctx.reporter.record_summary(
            self.experiment_name,
            result.summary,
            error_count=error_count,
            trial_stats=trial_stats(result.results, trials=self.ctx.trials),
            case_results=result.results,
        )

        if os.getenv("EXPORT_EVAL_RESULTS"):
            self._export_case_results(result)

        await self._enqueue_offline_upload(result)

    async def _enqueue_offline_upload(self, result: ExperimentResult) -> None:
        if self.offline_publisher is None or not self.send_to_posthog:
            return
        try:
            upload = await asyncio.to_thread(
                self.offline_publisher.prepare,
                experiment_id=self.experiment_id,
                experiment_name=self.experiment_name,
                started_at=self.started_at,
                result=result,
                metadata=self._experiment_metadata(),
            )
        except Exception as error:
            detail = str(error) if isinstance(error, OfflineUploadError) else type(error).__name__
            await self.ctx.reporter.record_posthog_offline_result(
                self.experiment_name, f"upload preparation failed: {detail}"
            )
            return

        delivery = self.ctx.offline_delivery
        if delivery is None:
            await self.ctx.reporter.record_posthog_offline_result(
                self.experiment_name,
                "upload failed: background delivery is unavailable. Results were not saved for retry.",
            )
            return
        await self.ctx.reporter.record_posthog_offline_result(self.experiment_name, "upload queued")
        if not delivery.submit(self.offline_publisher, upload):
            await self.ctx.reporter.record_posthog_offline_result(
                self.experiment_name, "upload failed: upload queue is full or closed. Results were not saved for retry."
            )

    def _export_case_results(self, result: ExperimentResult) -> None:
        """Write one JSONL row per case x trial to the run's local log dir.

        The reporter's ``eval_results.jsonl`` carries only per-experiment
        aggregates. The per-case records support paired case-level analysis. The data
        already lives in ``ExperimentResult.results``; persist it here.
        ``trial_index`` groups the trials of one case: scores from the same
        trial index are comparable across runs of the same case set, but a
        trial index is a repetition counter, not a fixed condition.
        """
        rows_by_trial: dict[str, int] = {}
        rows: list[dict[str, Any]] = []
        for case_result in result.results:
            case_name = case_result.input.get("name", "") if isinstance(case_result.input, dict) else ""
            if not case_name:
                continue
            trial_index = rows_by_trial.get(case_name, 0)
            rows_by_trial[case_name] = trial_index + 1
            rows.append(
                {
                    "run_id": self.experiment_id,
                    "experiment": self.experiment_name,
                    "case_name": case_name,
                    "trial_index": case_result.metadata.get("trial_index", trial_index),
                    "trial_id": case_result.metadata.get("trial_id"),
                    "scores": case_result.scores,
                    "error": case_result.error,
                    "phase_durations": case_result.metadata.get("phase_durations"),
                }
            )
        path = Path(self.run_log_dir) / "case_results.jsonl"
        try:
            with open(path, "wb") as f:
                for row in rows:
                    f.write(orjson.dumps(row) + b"\n")
        except OSError:
            logger.exception("Failed to export per-case results for '%s'", self.experiment_name)

    async def _report_results(self, result: ExperimentResult) -> None:
        for case_result in result.results:
            if trial_id := case_result.metadata.get("trial_id"):
                await self.ctx.reporter.case_scored(trial_id, error=case_result.error)

    async def run(self) -> ExperimentResult:
        eval_cases = self._build_eval_cases()

        if self.offline_suite is not None and self.send_to_posthog:
            try:
                settings = OfflineEvalSettings.from_env(self.offline_suite)
                if settings is not None:
                    self.offline_publisher = OfflineEvalPublisher(
                        settings,
                        self.offline_suite,
                        application_trace_ids_enabled=(
                            self.posthog_client is not None
                            and not self.posthog_client.disabled
                            and settings.host == self.ctx.posthog_trace_host
                            and settings.project_id == self.ctx.posthog_trace_project_id
                        ),
                    )
                else:
                    await self.ctx.reporter.record_posthog_offline_result(
                        self.experiment_name, "disabled: set POSTHOG_OFFLINE_EVAL_* to enable uploads"
                    )
            except OfflineUploadError as error:
                await self.ctx.reporter.record_posthog_offline_result(self.experiment_name, f"disabled: {error}")

        # Register the case total (post-filter, times trials) so the reporter can
        # append a per-experiment progress counter to each case line.
        planned_cases = len(eval_cases) * self.ctx.trials
        await self.ctx.reporter.experiment_started(
            self.experiment_name,
            planned_cases,
            self.run_log_dir,
            case_names=[str(case.input["name"]) for case in eval_cases],
        )

        try:
            result = await self.engine.run_experiment(
                ExperimentSpec(
                    project_name=self._project_name(),
                    cases=eval_cases,
                    task=self._task,
                    scorers=self.active_scorers,
                    trial_count=self.ctx.trials,
                    is_public=self.is_public,
                    no_send_logs=self.no_send_logs,
                    # Experiment names stay runtime/model-agnostic so history lines up across
                    # runs; the metadata is what lets an engine filter or compare by them.
                    metadata=self._experiment_metadata(),
                    on_results=self._report_results,
                    record_scorer_results=self.offline_publisher is not None,
                )
            )
            await self._report_results(result)
        finally:
            await self.ctx.reporter.finish_experiment(self.experiment_name)

        await self._finalize(result)
        return result


def _retryable_setup_error(error: Exception) -> bool:
    if isinstance(
        error,
        (
            ConnectionError,
            NetworkError,
            SocketTimeoutError,
            EndpointConnectionError,
            ConnectionClosedError,
            ReadTimeoutError,
            ClickHouseAtCapacity,
            ClickHouseQueryTimeOut,
            ClickHouseQueryMemoryLimitExceeded,
        ),
    ):
        return True
    if isinstance(error, ServerException):
        return error.code in {
            ErrorCodes.TIMEOUT_EXCEEDED,
            ErrorCodes.TOO_MANY_SIMULTANEOUS_QUERIES,
            ErrorCodes.MEMORY_LIMIT_EXCEEDED,
        }
    if isinstance(error, ClientError):
        return error.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in {500, 502, 503, 504}
    cause = error.__cause__ if isinstance(error, DjangoOperationalError) else error
    if isinstance(cause, PsycopgOperationalError):
        code = cause.sqlstate
        if code is not None:
            return code.startswith("08") or code in {"40001", "40P01", "53300", "57P01", "57P02", "57P03"}
        message = str(cause).lower()
        if "fatal:" in message:
            return False
        return any(
            transport_error in message
            for transport_error in (
                "connection refused",
                "connection reset by peer",
                "connection timed out",
                "timeout expired",
                "server closed the connection unexpectedly",
                "ssl syscall error: eof detected",
                "ssl connection has been closed unexpectedly",
                "could not receive data from server",
                "could not send data to server",
                "network is unreachable",
                "no route to host",
                "temporary failure in name resolution",
            )
        )
    return False


async def _run_setup_step[Result](step: Callable[[], Result]) -> Result:
    def run_in_worker() -> Result:
        try:
            return step()
        except Exception:
            close_old_connections()
            raise

    return await asyncio.to_thread(run_in_worker)


@frozen
class _SandboxedCaseSetup:
    context: CustomPromptSandboxContext
    seed: dict[str, Any]


class _SandboxedEvalRun(_BaseEvalRun):
    """The sandbox-agent incarnation of ``_BaseEvalRun``: per-case team
    provisioning, the sandbox-owning window, and ACP log post-processing.
    ``SandboxedEval`` is the thin public entry point."""

    trace_namespace = "sandboxed-agent"

    def __init__(
        self,
        experiment_name: str,
        cases: Sequence[SandboxedEvalCase],
        scorers: Sequence[Any],
        ctx: EvalContext,
        is_public: bool,
        no_send_logs: bool,
        offline_suite: OfflineEvalSuite | None = None,
        send_to_posthog: bool | None = None,
    ) -> None:
        if any(isinstance(scorer, ExitCodeZero) for scorer in scorers):
            raise ValueError("ExitCodeZero is added by the sandboxed eval harness; remove it from scorers")
        super().__init__(
            experiment_name=experiment_name,
            cases=cases,
            scorers=[ExitCodeZero(), *scorers],
            ctx=ctx,
            is_public=is_public,
            no_send_logs=no_send_logs,
            offline_suite=offline_suite,
            send_to_posthog=send_to_posthog,
        )
        # Narrow the infra-backed optionals once: they are None only when the
        # harness didn't boot sandbox infrastructure for this run.
        if ctx.provider_strategy is None or ctx.demo_data is None or ctx.sandbox_slots is None:
            raise RuntimeError(
                f"Suite '{experiment_name}' needs sandbox infrastructure that this run didn't boot; "
                "is its module missing the sandboxed SUITE_KIND?"
            )
        self._provider_strategy = ctx.provider_strategy
        self._demo_data = ctx.demo_data
        self._sandbox_slots = ctx.sandbox_slots

    def _case_input(self, case: BaseEvalCase) -> dict[str, Any]:
        assert isinstance(case, SandboxedEvalCase)
        return super()._case_input(case) | {"repo_fixture": case.repo_fixture}

    async def _prepare_case(
        self,
        eval_case: SandboxedEvalCase,
        original_case: SandboxedEvalCase | None,
        hooks: CaseHooks | None,
    ) -> _SandboxedCaseSetup:
        for attempt in range(self.ctx.infrastructure_retries + 1):
            if hooks is not None:
                hooks.metadata["setup_attempts"] = attempt + 1
            sandbox_context: CustomPromptSandboxContext | None = None
            try:
                # Team cloning and some case seeders both write to ClickHouse. Bound
                # the full setup phase separately even when Modal makes sandbox
                # capacity effectively unbounded.
                await self._set_case_phase(hooks, "queued")
                async with self.ctx.team_setup_slots:
                    await self._set_case_phase(hooks, "setup")
                    # The factory does Django ORM work. Django's async-safety
                    # guard rejects sync ORM calls from async contexts, so run it
                    # in a worker thread.
                    sandbox_context = await _run_setup_step(
                        partial(
                            self._demo_data.make_context,
                            eval_case.name,
                            disable_bundled_skills=(
                                self.ctx.skill_delivery == "exec"
                                or bool(original_case and original_case.disable_bundled_skills)
                            ),
                        ),
                    )
                    if original_case is not None and original_case.interaction_origin:
                        sandbox_context = replace(sandbox_context, interaction_origin=original_case.interaction_origin)
                    elif self.ctx.skill_delivery == "exec":
                        sandbox_context = replace(sandbox_context, interaction_origin=EVAL_INTERACTION_ORIGIN)
                    if sandbox_context.interaction_origin == "posthog_ai":
                        prompt = PromptService.build()
                        sandbox_context = replace(
                            sandbox_context,
                            system_prompt={
                                "type": prompt["type"],
                                "preset": prompt["preset"],
                                "append": prompt["append"],
                            },
                        )
                        if hooks is not None:
                            hooks.metadata["system_prompt_sha256"] = hashlib.sha256(
                                orjson.dumps(sandbox_context.system_prompt, option=orjson.OPT_SORT_KEYS)
                            ).hexdigest()
                    seed = (
                        await _run_setup_step(partial(original_case.setup, sandbox_context))
                        if original_case is not None and original_case.setup is not None
                        else {}
                    )
                return _SandboxedCaseSetup(context=sandbox_context, seed=seed)
            except Exception as error:
                if sandbox_context is not None:
                    await reclaim_kernels(
                        sandbox_context.team_id,
                        keep=self._provider_strategy.keeps_sandboxes(),
                    )
                if not _retryable_setup_error(error) or attempt == self.ctx.infrastructure_retries:
                    raise
                delay = infrastructure_retry_delay(attempt)
                error_type = type(error).__name__
                if hooks is not None:
                    hooks.metadata.setdefault("setup_retry_errors", []).append(error_type)
                await self.ctx.reporter.case_setup_retry(
                    self.experiment_name,
                    eval_case.name,
                    next_attempt=attempt + 2,
                    total_attempts=self.ctx.infrastructure_retries + 1,
                    delay_seconds=delay,
                    error_type=error_type,
                    trial_id=hooks.metadata.get("trial_id") if hooks is not None else None,
                )
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def _run_sandbox_window(
        self, eval_case: SandboxedEvalCase, original_case: SandboxedEvalCase | None, hooks: CaseHooks | None = None
    ) -> tuple[EvalCaseResult, dict[str, Any]]:
        """Run the sandbox-owning window and return its result plus the seed data.

        Holds a global sandbox slot for only this window: demo-data copy, setup
        hook, and the agent run. Everything after — log parsing, span building,
        trace emission, scoring — runs once the slot is freed, so a live sandbox
        never waits on post-processing.
        """
        ctx = self.ctx
        async with self._sandbox_slots:
            prepared = await self._prepare_case(eval_case, original_case, hooks)
            # Start the agent budget after team setup, so neither semaphore wait
            # nor the ClickHouse copy can consume it.
            try:
                with suppress(Exception):
                    await self._set_case_phase(hooks, "agent")
                result = await asyncio.wait_for(
                    run_eval_case(
                        eval_case,
                        prepared.context,
                        provider=self._provider_strategy,
                        on_cleanup=partial(self._set_case_phase, hooks, "cleanup"),
                        timeout_seconds=ctx.per_case_timeout_seconds,
                        on_poll_timeout=(
                            lambda error: (
                                hooks.metadata.update({"poll_timeout": error.diagnostics()})
                                if hooks is not None
                                else None
                            )
                        ),
                    ),
                    timeout=ctx.per_case_timeout_seconds,
                )
            finally:
                # Still inside the slot: a notebook python or duckdb cell provisions a
                # kernel sandbox of its own, and nothing else reclaims it. A timed-out
                # case is exactly the one most likely to have left one running. One
                # indexed query for every case that never touched a notebook.
                await reclaim_kernels(
                    prepared.context.team_id,
                    keep=self._provider_strategy is not None and self._provider_strategy.keeps_sandboxes(),
                )
        return result, prepared.seed

    async def _post_process(
        self,
        eval_case: SandboxedEvalCase,
        hooks: CaseHooks,
        result: EvalCaseResult,
        seed_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Build Braintrust spans, write local logs, emit trace events, and shape
        the scorer input dict — all off the sandbox slot."""
        # Store trace_id in metadata so evaluation events can link to the trace
        trial_id = hooks.metadata.get("trial_id", eval_case.name)
        if result.trace_id:
            hooks.metadata["trace_id"] = result.trace_id
            self.agent_trace_id_lookup[trial_id] = result.trace_id
        hooks.metadata["artifacts"] = result.artifacts.model_dump()

        # Parse the log once, use for both Braintrust spans and PostHog trace capture
        last_message = ""
        messages: list[dict[str, Any]] = []
        if result.raw_log:
            parsed = parse_log(result.raw_log, initial_prompt=eval_case.prompt)
            _log_conversation_spans(hooks, parsed)
            last_message = _get_last_assistant_text(parsed)
            messages = parsed.messages

            if self.posthog_client:
                try:
                    emit_trace_events(
                        self.posthog_client,
                        trace_id=result.trace_id,
                        experiment_id=self.experiment_id,
                        experiment_name=self.experiment_name,
                        case_name=eval_case.name,
                        parsed=parsed,
                        namespace=self.trace_namespace,
                        run_metadata=self._experiment_metadata(),
                    )
                    # Store metadata for emit_trace_root (called after scoring)
                    self.case_trace_meta[trial_id] = {
                        "prompt": eval_case.prompt,
                        "duration": result.artifacts.duration_seconds,
                        "first_timestamp": parsed.first_timestamp,
                        "last_message": last_message,
                        "artifacts_summary": result.artifacts.model_dump(),
                        "token_usage": parsed.total_token_usage,
                    }
                except Exception:
                    logger.exception("Failed to emit trace events for '%s'", eval_case.name)

        try:
            write_case_logs(
                case_dir=self.run_log_dir,
                case_name=eval_case.name,
                raw_log=result.raw_log or "",
                artifacts=result.artifacts.model_dump(),
                prompt=eval_case.prompt,
                duration=result.artifacts.duration_seconds,
                last_message=last_message,
                token_usage=self.case_trace_meta.get(trial_id, {}).get("token_usage"),
                trial_id=hooks.metadata.get("trial_id"),
                trace_id=result.trace_id,
            )
        except Exception:
            logger.exception("Failed to write local eval logs for '%s'", eval_case.name)

        # After the logs are on disk, so a failed run is still there to read.
        if agent_never_ran(result.artifacts):
            raise AgentNeverRanError(
                f"Eval case '{eval_case.name}' failed before doing any work: {result.artifacts.stderr}"
            )

        return result.artifacts.model_dump() | {
            "last_message": last_message,
            "messages": messages,
            "raw_log": result.raw_log,
            "turn_logs": result.turn_logs,
            "turn_prompts": [eval_case.prompt, *eval_case.followups],
            "seed": seed_result,
            "prompt": eval_case.prompt,
        }

    async def _execute_case(self, input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        eval_case = SandboxedEvalCase(
            name=input["name"],
            prompt=input["prompt"],
            followups=list(input.get("followups") or []),
            repo_fixture=input.get("repo_fixture", ""),
        )
        original_case = self.cases_by_name.get(input["name"])
        sandbox_case = original_case if isinstance(original_case, SandboxedEvalCase) else None
        result, seed_result = await self._run_sandbox_window(eval_case, sandbox_case, hooks)
        await self._set_case_phase(hooks, "logs")
        return await self._post_process(eval_case, hooks, result, seed_result)

    def _timeout_output(self) -> dict[str, Any]:
        return AgentArtifacts(
            exit_code=1,
            stderr=f"case timeout after {self.ctx.per_case_timeout_seconds}s",
        ).model_dump()

    def _project_name(self) -> str:
        return f"sandboxed-agent-{self.experiment_name}" if self.is_public else self.experiment_name

    def _experiment_metadata(self) -> RunMetadata:
        return {
            **super()._experiment_metadata(),
            "agent_runtime": self.ctx.agent_runtime,
            "skill_delivery": self.ctx.skill_delivery,
            "reasoning_effort": self.ctx.reasoning_effort,
        }


async def SandboxedEval(
    experiment_name: str,
    cases: Sequence[SandboxedEvalCase],
    scorers: Sequence[Any],
    ctx: EvalContext,
    is_public: bool = False,
    no_send_logs: bool = True,
    offline_suite: OfflineEvalSuite | None = None,
    send_to_posthog: bool | None = None,
) -> ExperimentResult:
    """Run a sandboxed agent evaluation suite via Braintrust.

    For each ``SandboxedEvalCase``, creates a Task, triggers the temporal workflow
    (sandbox provisioning, agent-server, prompt delivery, cleanup), polls S3 logs
    for results, and feeds parsed artifacts to the scorers.

    ``ctx.demo_data.make_context(case_name)`` is invoked once per case and
    returns a freshly isolated ``CustomPromptSandboxContext`` (own org/team/user)
    so cases can't pollute each other's state.

    Everything the suite needs (demo data, analytics client, case filter,
    concurrency limits, reporter) comes off ``ctx``; suites run concurrently on
    one event loop, with sandbox load bounded by ``ctx.sandbox_slots`` and team
    setup serialized by ``ctx.team_setup_slots``.
    """
    run = _SandboxedEvalRun(
        experiment_name=experiment_name,
        cases=cases,
        scorers=scorers,
        ctx=ctx,
        is_public=is_public,
        no_send_logs=no_send_logs,
        offline_suite=offline_suite,
        send_to_posthog=send_to_posthog,
    )
    return await run.run()


SandboxedPublicEval = partial(SandboxedEval, is_public=True, no_send_logs=False)
"""Sandboxed evaluation case that is publicly accessible."""

SandboxedPrivateEval = partial(SandboxedEval, is_public=False, no_send_logs=True)
"""Sandboxed evaluation case that is not accessible publicly."""
