from __future__ import annotations

import time
import uuid
import asyncio
import logging
from collections.abc import Sequence
from functools import partial
from typing import TYPE_CHECKING, Any, Literal

from .acp_log import ParsedLog, parse_log
from .config import AgentArtifacts, BaseEvalCase, SandboxedEvalCase
from .engines.base import EvalEngine
from .engines.types import CaseHooks, CaseSpec, ExperimentResult, ExperimentSpec, SpanKind
from .log_sink import append_case_scores, build_case_dir, write_case_logs
from .runner import EvalCaseResult, run_eval_case
from .scorers import ExitCodeZero, wrap_scorers
from .trace_events import emit_evaluation_events, emit_trace_events, emit_trace_root

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
                    parts.append(f"[tool_use: {block.get('name', '?')}]")
                elif block_type == "tool_result":
                    result_text = str(block.get("content", ""))[:500]
                    is_error = block.get("is_error", False)
                    prefix = "[tool_result error]" if is_error else "[tool_result]"
                    parts.append(f"{prefix} {result_text}")
            display_content = "\n".join(parts)
        else:
            display_content = str(content)

        span_type: SpanKind
        if role == "assistant":
            # Check if this message contains tool_use blocks
            has_tool_use = isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content
            )
            span_type = "function" if has_tool_use else "llm"
            name = "tool_call" if has_tool_use else "agent"
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
    """Prefix for the experiment name in scorer trace metadata."""

    def __init__(
        self,
        experiment_name: str,
        cases: Sequence[BaseEvalCase],
        scorers: Sequence[Any],
        ctx: EvalContext,
        is_public: bool,
        no_send_logs: bool,
        engine: EvalEngine | None = None,
    ) -> None:
        self.experiment_name = experiment_name
        self.cases = cases
        self.ctx = ctx
        self.is_public = is_public
        self.no_send_logs = no_send_logs
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
        return {"name": case.name, "prompt": case.prompt}

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

    def _experiment_metadata(self) -> dict[str, Any]:
        return {"agent_model": self.ctx.agent_model}

    async def _task(self, input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any] | None:
        case_started = time.monotonic()
        case_name = input.get("name", "?")
        status: Literal["ok", "timeout", "error"] = "ok"
        try:
            return await self._execute_case(input, hooks)
        except TimeoutError:
            # A case that outran its budget is a task result (too slow), not an
            # infra error: score it 0 rather than letting Braintrust mark it errored.
            status = "timeout"
            logger.warning("Eval case '%s' timed out after %ds", case_name, self.ctx.per_case_timeout_seconds)
            return self._timeout_output()
        except Exception:
            # Infra failure (provisioning, demo copy, setup hook, poll). Re-raise so
            # Braintrust records the case as errored and excludes it from score
            # averages, instead of scoring the task 0 for the harness's fault.
            status = "error"
            logger.exception("Eval task errored for '%s'", case_name)
            raise
        finally:
            # Report on every path so the reporter's live case counter never stalls.
            await self.ctx.reporter.case_done(
                self.experiment_name,
                case_name,
                duration_seconds=time.monotonic() - case_started,
                status=status,
            )

    async def _finalize(self, result: ExperimentResult) -> None:
        """Append scores to local summaries, emit PostHog evaluation/trace-root
        events, and hand the summary to the reporter — after scoring completes."""
        # Append final scores to local summary files for every case we wrote.
        if result.results:
            for eval_result in result.results:
                case_name = eval_result.input.get("name", "") if isinstance(eval_result.input, dict) else ""
                if not case_name:
                    continue
                try:
                    append_case_scores(self.run_log_dir, case_name, dict(eval_result.scores or {}))
                except Exception:
                    logger.exception("Failed to append scores to local log summary for '%s'", case_name)

        # Emit evaluation events and trace roots to PostHog (after scoring)
        if self.posthog_client and result.results:
            try:
                emit_evaluation_events(
                    self.posthog_client, self.experiment_id, self.experiment_name, result.results, self.scorer_traces
                )
                # Emit $ai_trace root events now that scores are available
                for eval_result in result.results:
                    case_name = eval_result.input.get("name", "") if isinstance(eval_result.input, dict) else ""
                    trace_id = self.agent_trace_id_lookup.get(case_name)
                    meta = self.case_trace_meta.get(case_name)
                    if trace_id and meta:
                        emit_trace_root(
                            self.posthog_client,
                            trace_id=trace_id,
                            experiment_id=self.experiment_id,
                            experiment_name=self.experiment_name,
                            case_name=case_name,
                            prompt=meta["prompt"],
                            duration=meta["duration"],
                            first_timestamp=meta["first_timestamp"],
                            last_message=meta.get("last_message", ""),
                            artifacts_summary=meta.get("artifacts_summary"),
                            scores=eval_result.scores,
                            token_usage=meta.get("token_usage"),
                        )
                self.posthog_client.flush()
                await self.ctx.reporter.record_posthog_evaluations_url(self.experiment_name, self.experiment_id)
            except Exception:
                logger.exception("Failed to emit evaluation events for '%s'", self.experiment_name)

        # Hand the summary to the reporter: suites don't return their Braintrust
        # result up to the orchestrator, so this is the only place the final table
        # and the EXPORT_EVAL_RESULTS jsonl can read per-scorer scores from.
        # Errored cases (infra failures) are surfaced separately so they read as noise,
        # not as agent 0s dragging the averages.
        error_count = sum(1 for r in result.results if r.error is not None)
        await self.ctx.reporter.record_summary(self.experiment_name, result.summary, error_count=error_count)

    async def run(self) -> ExperimentResult:
        eval_cases = self._build_eval_cases()

        # Register the case total (post-filter, times trials) so the reporter can
        # append a per-experiment progress counter to each case line.
        planned_cases = len(eval_cases) * self.ctx.trials
        await self.ctx.reporter.experiment_started(self.experiment_name, planned_cases, self.run_log_dir)

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
            )
        )

        await self._finalize(result)
        return result


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

    async def _run_sandbox_window(
        self, eval_case: SandboxedEvalCase, original_case: SandboxedEvalCase | None
    ) -> tuple[EvalCaseResult, dict[str, Any]]:
        """Run the sandbox-owning window and return its result plus the seed data.

        Holds a global sandbox slot for only this window: demo-data copy, setup
        hook, and the agent run. Everything after — log parsing, span building,
        trace emission, scoring — runs once the slot is freed, so a live sandbox
        never waits on post-processing.
        """
        ctx = self.ctx
        seed_result: dict[str, Any] = {}
        async with self._sandbox_slots:
            # Team cloning and some case seeders both write to ClickHouse. Bound
            # the full setup phase separately even when Modal makes sandbox
            # capacity effectively unbounded.
            async with ctx.team_setup_slots:
                # The factory does Django ORM work. Django's async-safety
                # guard rejects sync ORM calls from async contexts, so run it
                # in a worker thread.
                sandbox_context = await asyncio.to_thread(self._demo_data.make_context, eval_case.name)
                if original_case is not None and original_case.setup is not None:
                    try:
                        seed_result = await asyncio.to_thread(original_case.setup, sandbox_context)
                    except Exception:
                        logger.exception("Setup hook failed for '%s'", eval_case.name)
                        raise
            # Start the agent budget after team setup, so neither semaphore wait
            # nor the ClickHouse copy can consume it.
            result = await asyncio.wait_for(
                run_eval_case(eval_case, sandbox_context, provider=self._provider_strategy),
                timeout=ctx.per_case_timeout_seconds,
            )
        return result, seed_result

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
        if result.trace_id:
            hooks.metadata["trace_id"] = result.trace_id
            self.agent_trace_id_lookup[eval_case.name] = result.trace_id
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
                    )
                    # Store metadata for emit_trace_root (called after scoring)
                    self.case_trace_meta[eval_case.name] = {
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
                token_usage=self.case_trace_meta.get(eval_case.name, {}).get("token_usage"),
            )
        except Exception:
            logger.exception("Failed to write local eval logs for '%s'", eval_case.name)

        return result.artifacts.model_dump() | {
            "last_message": last_message,
            "messages": messages,
            "raw_log": result.raw_log,
            "seed": seed_result,
            "prompt": eval_case.prompt,
        }

    async def _execute_case(self, input: dict[str, Any], hooks: CaseHooks) -> dict[str, Any]:
        eval_case = SandboxedEvalCase(
            name=input["name"],
            prompt=input["prompt"],
            repo_fixture=input.get("repo_fixture", ""),
        )
        original_case = self.cases_by_name.get(input["name"])
        sandbox_case = original_case if isinstance(original_case, SandboxedEvalCase) else None
        result, seed_result = await self._run_sandbox_window(eval_case, sandbox_case)
        return await self._post_process(eval_case, hooks, result, seed_result)

    def _timeout_output(self) -> dict[str, Any]:
        return AgentArtifacts(
            exit_code=1,
            stderr=f"case timeout after {self.ctx.per_case_timeout_seconds}s",
        ).model_dump()

    def _project_name(self) -> str:
        return f"sandboxed-agent-{self.experiment_name}" if self.is_public else self.experiment_name

    def _experiment_metadata(self) -> dict[str, Any]:
        return {"agent_model": self.ctx.agent_model, "agent_runtime": self.ctx.agent_runtime}


async def SandboxedEval(
    experiment_name: str,
    cases: Sequence[SandboxedEvalCase],
    scorers: Sequence[Any],
    ctx: EvalContext,
    is_public: bool = False,
    no_send_logs: bool = True,
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
    )
    return await run.run()


SandboxedPublicEval = partial(SandboxedEval, is_public=True, no_send_logs=False)
"""Sandboxed evaluation case that is publicly accessible."""

SandboxedPrivateEval = partial(SandboxedEval, is_public=False, no_send_logs=True)
"""Sandboxed evaluation case that is not accessible publicly."""
