"""Step runners: invoke a production agentic step under a chosen backend.

Each runner owns the knowledge of *how to call one production step function* and what
extra (non-agent) infrastructure that step touches so a deterministic replay can stub it.
The harness owns the generic concerns (timing, scoring, results) and stays step-agnostic.

Modes:

- ``replay``  — inject :class:`ReplayMultiTurnSession`, feed the case's cassette, stub the
  step's DB/network helpers. No stack, no LLM, deterministic.
- ``record``  — live run via :class:`RecordingMultiTurnSession`, persisting a cassette.
- ``live``    — the real step function end to end (needs the local stack + Docker).

Research and repo-selection drive ``MultiTurnSession`` so they share the replay machinery.
Implementation is a coding-agent task that yields a diff; its "output" is a unified patch,
replayed from a recorded patch file and graded by diff scorers.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from unittest.mock import patch as mock_patch

from products.signals.eval.agentic.cassette import Cassette
from products.signals.eval.agentic.datasets import EvalCase, ImplementationCase, RepoSelectionCase, ResearchCase
from products.signals.eval.agentic.session_backends import (
    RecordingMultiTurnSession,
    ReplayMultiTurnSession,
    _Recorder,
    active_cassette,
    active_recorder,
    inject_session,
    recorder_to_cassette,
)

if TYPE_CHECKING:
    from products.signals.backend.agent_runtime import AgentRuntime
    from products.signals.backend.report_generation.research import ReportResearchOutput

logger = logging.getLogger(__name__)


class RunnerError(RuntimeError):
    """A runner could not produce an output (bad case wiring, missing cassette, etc.)."""


class RunContext:
    """Per-run dependencies a runner needs. Live mode fills team/user/sandbox; replay ignores them."""

    def __init__(
        self,
        *,
        team_id: int = 1,
        user_id: int = 1,
        cassette_dir: Path | None = None,
        sandbox_environment_id: str | None = None,
    ):
        self.team_id = team_id
        self.user_id = user_id
        self.cassette_dir = cassette_dir or (Path(__file__).parent / "cases" / "cassettes")
        self.sandbox_environment_id = sandbox_environment_id


class StepRunner(Protocol):
    step: str

    async def run(self, case: EvalCase, *, mode: str, ctx: RunContext, meta: dict[str, Any] | None = None) -> Any: ...

    def input_repr(self, case: EvalCase) -> str: ...

    def output_repr(self, output: Any) -> str: ...


@contextmanager
def _patched(targets: dict[str, Any]) -> Iterator[None]:
    """Patch ``"module.path.attr" -> value`` for the block (ExitStack of mock.patch)."""
    with ExitStack() as stack:
        for dotted, value in targets.items():
            stack.enter_context(mock_patch(dotted, value))
        yield


@contextmanager
def _no_db() -> Iterator[None]:
    """Fail fast on any DB access — replay must stay persistence-free (`signal_report_id=None` invariant)."""

    def _blocked(self_: Any) -> None:
        raise RuntimeError("signals agentic replay attempted a database connection — replay must be persistence-free")

    with mock_patch("django.db.backends.base.base.BaseDatabaseWrapper.ensure_connection", _blocked):
        yield


async def _resolve_runtime(team_id: int, step: str) -> AgentRuntime:
    """Resolve the `signals-pipeline-models` override the way the production activities do."""
    from posthog.sync import database_sync_to_async  # noqa: PLC0415

    from products.signals.backend.agent_runtime import resolve_agent_runtime  # noqa: PLC0415

    # Off the event loop: the payload read is blocking network I/O.
    return await database_sync_to_async(resolve_agent_runtime, thread_sensitive=False)(team_id, step)


def _runtime_meta(runtime: AgentRuntime) -> dict[str, str]:
    values = {"adapter": runtime.runtime_adapter, "model": runtime.model, "effort": runtime.reasoning_effort}
    # All-None (the agent-server default) reports as {} — the report layer shows nothing for it.
    return {key: value for key, value in values.items() if value is not None}


def _build_sandbox_context(ctx: RunContext, repository: str | None, runtime: AgentRuntime | None = None) -> Any:
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext  # noqa: PLC0415

    return CustomPromptSandboxContext(
        team_id=ctx.team_id,
        user_id=ctx.user_id,
        repository=repository,
        sandbox_environment_id=ctx.sandbox_environment_id,
        posthog_mcp_scopes="read_only",
        model=runtime.model if runtime else None,
        runtime_adapter=runtime.runtime_adapter if runtime else None,
        reasoning_effort=runtime.reasoning_effort if runtime else None,
    )


def _load_cassette(case: EvalCase, ctx: RunContext) -> Cassette:
    if not case.cassette:
        raise RunnerError(f"case {case.case_id!r} has no cassette for replay mode")
    path = ctx.cassette_dir / case.cassette
    if not path.exists():
        raise RunnerError(f"cassette not found: {path}")
    return Cassette.load(path)


def _save_recorded_cassette(recorder: _Recorder, case: EvalCase, ctx: RunContext, *, meta: dict | None = None) -> None:
    if not recorder.turns:
        raise RunnerError(
            f"record run for case {case.case_id!r} captured no turns — refusing to overwrite the cassette "
            "(is a MultiTurnSession bind site missing from _PATCH_TARGETS?)"
        )
    recorder_to_cassette(recorder, meta=meta).save(ctx.cassette_dir / (case.cassette or f"{case.case_id}.json"))


# ── Research ─────────────────────────────────────────────────────────────────────


class ResearchRunner:
    step = "research"

    async def run(
        self, case: EvalCase, *, mode: str, ctx: RunContext, meta: dict[str, Any] | None = None
    ) -> ReportResearchOutput:
        assert isinstance(case, ResearchCase)
        from products.signals.backend.report_generation.research import run_multi_turn_research  # noqa: PLC0415

        signals = [spec.to_signal_data() for spec in case.signals]
        runtime = None
        if mode in ("live", "record"):
            # Same per-team/per-step resolution as run_agentic_report_activity, so the
            # `signals-pipeline-models` payload controls the model under eval too.
            runtime = await _resolve_runtime(ctx.team_id, self.step)
            if meta is not None:
                meta["runtime"] = _runtime_meta(runtime)
        sandbox_context = _build_sandbox_context(ctx, case.repo, runtime=runtime)
        # Live/record stream progress to stderr; replay is silent (no agent to narrate).
        output_fn = (lambda msg: logger.info("research[%s]: %s", case.case_id, msg)) if mode != "replay" else None

        async def _invoke() -> ReportResearchOutput:
            # signal_report_id=None keeps research persistence-free (no DB writes), so replay
            # runs with no database — see report_generation/CLAUDE.md.
            return await run_multi_turn_research(
                signals,
                sandbox_context,
                title=case.title,
                summary=case.summary,
                signal_report_id=None,
                verbose=mode != "replay",
                output_fn=output_fn,
            )

        if mode == "replay":
            cassette = _load_cassette(case, ctx)
            with inject_session(ReplayMultiTurnSession), active_cassette(cassette), _no_db():
                return await _invoke()
        if mode == "record":
            with inject_session(RecordingMultiTurnSession), active_recorder(case.case_id, self.step) as recorder:
                output = await _invoke()
            _save_recorded_cassette(recorder, case, ctx)
            return output
        if mode == "live":
            return await _invoke()
        raise RunnerError(f"unknown mode {mode!r}")

    def input_repr(self, case: EvalCase) -> str:
        assert isinstance(case, ResearchCase)
        return "\n\n".join(s.content for s in case.signals)

    def output_repr(self, output: ReportResearchOutput) -> str:
        findings = output.effective_findings()
        lines = [f"title: {output.title}", f"summary: {output.summary[:400]}"]
        for f in findings:
            lines.append(
                f"finding[{f.signal_id}] paths={f.relevant_code_paths} verified={f.verified} "
                f"data_queried={f.data_queried[:200]!r}"
            )
        try:
            act = output.effective_actionability()
            lines.append(f"actionability: {act.actionability.value} already_addressed={act.already_addressed}")
        except ValueError:
            lines.append("actionability: <none>")
        prio = output.effective_priority()
        lines.append(f"priority: {prio.priority.value if prio else '<none>'}")
        return "\n".join(lines)


# ── Repository selection ───────────────────────────────────────────────────────────


class RepoSelectionRunner:
    step = "repo_selection"

    async def run(self, case: EvalCase, *, mode: str, ctx: RunContext, meta: dict[str, Any] | None = None) -> Any:
        assert isinstance(case, RepoSelectionCase)
        from products.signals.backend.report_generation.select_repo import select_repository_for_team  # noqa: PLC0415
        from products.signals.backend.temporal.types import render_signals_to_text  # noqa: PLC0415

        context_text = case.context or render_signals_to_text([s.to_signal_data() for s in case.signals])
        if mode in ("live", "record") and meta is not None:
            # select_repository_for_team resolves the runtime itself; re-resolve only to report it.
            meta["runtime"] = _runtime_meta(await _resolve_runtime(ctx.team_id, self.step))

        async def _invoke() -> Any:
            return await select_repository_for_team(
                ctx.team_id,
                ctx.user_id,
                context_text,
                signal_report_id=None,
            )

        if mode == "replay":
            cassette = _load_cassette(case, ctx)
            candidates = self._replay_candidates(case, cassette)
            with (
                inject_session(ReplayMultiTurnSession),
                active_cassette(cassette),
                self._replay_patches(candidates),
            ):
                return await _invoke()
        if mode == "record":
            shown: dict[str, list[str]] = {}
            with (
                inject_session(RecordingMultiTurnSession),
                active_recorder(case.case_id, self.step) as recorder,
                self._capture_candidates(shown),
            ):
                output = await _invoke()
            _save_recorded_cassette(
                recorder, case, ctx, meta={"candidates": shown["final"]} if shown.get("final") else None
            )
            return output
        if mode == "live":
            return await _invoke()
        raise RunnerError(f"unknown mode {mode!r}")

    @staticmethod
    def _replay_candidates(case: RepoSelectionCase, cassette: Cassette) -> list[str]:
        """Prefer the candidate list the recorded agent was actually shown over the case's list."""
        recorded = cassette.meta.get("candidates")
        if not (isinstance(recorded, list) and recorded):
            return [r.lower() for r in case.candidate_repos]
        candidates = [str(r).lower() for r in recorded]
        case_list = [r.lower() for r in case.candidate_repos]
        if case_list and case_list != candidates:
            logger.warning(
                "repo_selection[%s]: cassette recorded candidates %s differ from the case list %s — replaying "
                "with the recorded ones",
                case.case_id,
                candidates,
                case_list,
            )
        return candidates

    @contextmanager
    def _capture_candidates(self, shown: dict[str, list[str]]) -> Iterator[None]:
        """Capture the eligible candidate list a live record run shows the agent, for the cassette meta."""
        from products.tasks.backend.logic.repo_selection import agent as rs_agent  # noqa: PLC0415

        real_candidates = rs_agent._list_candidate_repos
        real_eligible = rs_agent._list_eligible_full_names

        def _capturing_candidates(github: Any, team_id: int) -> list[str]:
            result = real_candidates(github, team_id)
            shown["candidates"] = list(result)
            return result

        def _capturing_eligible(github: Any, team_id: int) -> set[str]:
            result = real_eligible(github, team_id)
            # Mirror select_repository's eligibility filter so the meta holds what the agent saw.
            shown["final"] = [r for r in shown.get("candidates", []) if r in result]
            return result

        with _patched(
            {
                "products.tasks.backend.logic.repo_selection.agent._list_candidate_repos": _capturing_candidates,
                "products.tasks.backend.logic.repo_selection.agent._list_eligible_full_names": _capturing_eligible,
            }
        ):
            yield

    @contextmanager
    def _replay_patches(self, candidates: list[str]) -> Iterator[None]:
        """Stub the DB/network around repo selection so replay needs no stack.

        We keep the real signals chokepoint (``select_repository_for_team`` →
        ``select_repository``) and its rejection/validation logic, and only neutralize the
        GitHub-integration resolution and repo-cache hydration that would otherwise hit
        Postgres + the GitHub API.
        """
        from products.signals.backend import agent_runtime  # noqa: PLC0415

        async def _noop_sync_full_cache(self_) -> None:
            return None

        class _FakeGithub:
            class _Int:
                id = 0

            integration = _Int()

        with _patched(
            {
                "products.signals.backend.report_generation.select_repo.resolve_agent_runtime": (
                    lambda team_id, step: agent_runtime.DEFAULT_RUNTIME
                ),
                "products.tasks.backend.logic.repo_selection.agent.resolve_team_github_integration": (
                    lambda team_id, team=None: _FakeGithub()
                ),
                "products.tasks.backend.logic.repo_selection.agent._list_candidate_repos": (
                    lambda github, team_id: list(candidates)
                ),
                "products.tasks.backend.logic.repo_selection.agent._list_eligible_full_names": (
                    lambda github, team_id: set(candidates)
                ),
                "products.tasks.backend.logic.repo_selection.agent.GitHubRepositoryFullCache.sync_full_cache": (
                    _noop_sync_full_cache
                ),
            }
        ):
            yield

    def input_repr(self, case: EvalCase) -> str:
        assert isinstance(case, RepoSelectionCase)
        return f"candidates={list(case.candidate_repos)}\ncontext={case.context or '<signals>'}"

    def output_repr(self, output: Any) -> str:
        return f"repository={output.repository} reason={output.reason}"


# ── Implementation ───────────────────────────────────────────────────────────────


class ImplementationOutput:
    """The gradeable artifact of an implementation run: a unified diff and its file list."""

    def __init__(self, diff: str):
        self.diff = diff
        self.files_changed = _files_from_diff(diff)


def _build_impl_prompt(case: ImplementationCase, full_name: str) -> str:
    return f"""You are a coding agent. The repository `{full_name}` is checked out on disk.

## Task
{case.issue_prompt}

## Instructions
1. Locate the relevant code, then implement the change with a minimal, focused edit. Stay strictly
   on-topic — do not refactor unrelated code or touch lock files.
2. After editing, run `git add -A` then `git diff --cached` to produce the unified diff of your change.
3. Respond with a JSON object: `diff` is the exact unified diff from `git diff --cached` (the full
   patch, including the `diff --git` headers), and `summary` is one sentence on what you changed.
Do not open a pull request or push; just make the local edit and report the diff."""


def _files_from_diff(diff: str) -> list[str]:
    """File paths from a unified diff's per-file headers.

    Only trusts ``---``/``+++`` (and rename/copy) lines in header position — between a
    ``diff --git`` line and the first hunk — because hunk body lines can legitimately
    start with ``--- ``/``+++ `` (e.g. a removed SQL ``-- comment`` line).
    """
    files: list[str] = []

    def _add(path: str) -> None:
        for prefix in ("a/", "b/"):
            if path.startswith(prefix):
                path = path[len(prefix) :]
        if path and path != "/dev/null" and path not in files:
            files.append(path)

    in_header = False
    for raw in diff.splitlines():
        if raw.startswith("diff --git "):
            in_header = True
            parts = raw.split()
            if len(parts) >= 4:
                _add(parts[2])
        elif raw.startswith("@@"):
            in_header = False
        elif in_header and raw.startswith(("rename to ", "copy to ")):
            _add(raw.split(" ", 2)[2].strip())
        elif in_header and raw.startswith(("--- ", "+++ ")):
            _add(raw[4:].strip())
            if raw.startswith("+++ "):
                in_header = False
    return files


class ImplementationRunner:
    step = "implementation"

    async def run(
        self, case: EvalCase, *, mode: str, ctx: RunContext, meta: dict[str, Any] | None = None
    ) -> ImplementationOutput:
        assert isinstance(case, ImplementationCase)
        if mode == "replay":
            if not case.patch:
                raise RunnerError(f"implementation case {case.case_id!r} has no recorded patch for replay")
            patch_path = ctx.cassette_dir / case.patch
            if not patch_path.exists():
                raise RunnerError(f"patch not found: {patch_path}")
            return ImplementationOutput(patch_path.read_text(encoding="utf-8"))
        if mode in ("live", "record"):
            return await self._run_live(case, ctx, record=mode == "record", meta=meta)
        raise RunnerError(f"unknown mode {mode!r}")

    async def _run_live(
        self, case: ImplementationCase, ctx: RunContext, *, record: bool, meta: dict[str, Any] | None = None
    ) -> ImplementationOutput:
        """Drive the coding agent against the checked-out repo and capture its unified diff.

        Reuses the same ``MultiTurnSession`` seam as the other steps: the agent edits files in the
        sandbox and returns the diff as structured output, which the diff scorers grade. This is the
        agent's implementation capability (edit + report), distinct from the production flow that
        also opens a PR — see README. Requires the local stack + Docker sandbox.
        """
        from pydantic import BaseModel, Field  # noqa: PLC0415

        from products.signals.eval.agentic import repos as repo_registry  # noqa: PLC0415
        from products.tasks.backend.facade import api as tasks_facade  # noqa: PLC0415
        from products.tasks.backend.facade.agents import MultiTurnSession  # noqa: PLC0415

        class ImplementationDiffOutput(BaseModel):
            diff: str = Field(description="The full unified diff from `git diff --cached`.")
            summary: str = Field(description="One sentence describing the change.")

        # "implementation" isn't a payload step name — coding-agent runs resolve
        # via the custom_agent slot, matching the production autostart analog.
        runtime = await _resolve_runtime(ctx.team_id, "custom_agent")
        if meta is not None:
            meta["runtime"] = _runtime_meta(runtime)
        full_name = repo_registry.get(case.repo).full_name if case.repo in repo_registry.REGISTRY else case.repo
        context = _build_sandbox_context(ctx, full_name, runtime=runtime)
        session, result = await MultiTurnSession.start(
            prompt=_build_impl_prompt(case, full_name),
            context=context,
            model=ImplementationDiffOutput,
            step_name="implementation",
            origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
            ai_stage="implementation",
            internal=True,
            verbose=True,
            output_fn=lambda msg: logger.info("impl[%s]: %s", case.case_id, msg),
        )
        try:
            diff = result.diff
        finally:
            await session.end()
        if record:
            patch_path = ctx.cassette_dir / (case.patch or f"{case.case_id}.patch")
            patch_path.parent.mkdir(parents=True, exist_ok=True)
            patch_path.write_text(diff, encoding="utf-8")
            logger.info("impl[%s]: recorded diff to %s", case.case_id, patch_path)
        return ImplementationOutput(diff)

    def input_repr(self, case: EvalCase) -> str:
        assert isinstance(case, ImplementationCase)
        return f"repo={case.repo}\nissue={case.issue_prompt}"

    def output_repr(self, output: ImplementationOutput) -> str:
        return f"files_changed={output.files_changed}\n--- diff (truncated) ---\n{output.diff[:1200]}"


RUNNERS: dict[str, StepRunner] = {
    ResearchRunner.step: ResearchRunner(),
    RepoSelectionRunner.step: RepoSelectionRunner(),
    ImplementationRunner.step: ImplementationRunner(),
}
