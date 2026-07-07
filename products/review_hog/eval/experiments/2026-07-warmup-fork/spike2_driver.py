"""Spike 2 driver — stripped-form fork fidelity (M3 go/no-go, see PLAN.md).

Creates warm-up session A (neutral read of PR #62096's core files + a settling
turn, on a 1h-TTL sandbox env), waits for A's raw-transcript artifact, then
launches two concurrent followers B and C that fork A's run. Prints ids and
wall-clock marks; the fidelity/latency analysis runs post-hoc over
`$ai_generation` (gates in PLAN.md M3).

Run (stack + ngrok up, patched local agent build live, worker restarted):
  flox activate -- bash -c \
    'python manage.py shell < products/review_hog/eval/experiments/2026-07-warmup-fork/spike2_driver.py'
"""

# ruff: noqa: T201 — throwaway spike driver, stdout is the intended output channel

import time
import asyncio
from datetime import UTC, datetime

from asgiref.sync import sync_to_async
from pydantic import BaseModel

from posthog.models import Team, User

from products.review_hog.backend.reviewer.constants import REVIEW_MODEL, REVIEW_REASONING_EFFORT, REVIEW_RUNTIME_ADAPTER
from products.tasks.backend.facade.agents import CustomPromptSandboxContext, MultiTurnSession
from products.tasks.backend.models import SandboxEnvironment, TaskRun

TEAM_ID = 1
USER_ID = 1
REPOSITORY = "PostHog/posthog"
BRANCH = "posthog-code/max-action-tools"  # PR #62096, frozen eval fixture

WARMUP_PROMPT = """You are preparing the ground for a code review of this branch. READ ONLY: no judgments, no analysis, no opinions, no code changes, and do not describe problems even if you notice them.

1. Read these changed files fully: ee/hogai/tools/actions/core.py, ee/hogai/tools/actions/tool.py, ee/hogai/chat_agent/toolkit.py
2. For each, grep for its direct importers/callers and read the 1-2 most relevant caller files.
3. Read ee/hogai/tools/actions/test/test_action_tools.py.

End your turn with JSON only: {"files_read": ["..."], "status": "done"}"""

SETTLE_PROMPT = 'Investigation complete. Reply with JSON only: {"status": "ready"}'

FOLLOWER_PROMPT = """A prior read-only investigation of this branch's changed files (ee/hogai/tools/actions/* and their callers) is already in your context. Reuse it: do not re-read files it already covered unless you genuinely need a detail it lacks.

Question: which single changed function has the widest blast radius (most distinct callers), and why?

End your turn with JSON only: {"answer": "...", "re_read_files": ["files you re-read, if any"]}"""


class WarmUpOut(BaseModel):
    files_read: list[str]
    status: str


class Ack(BaseModel):
    status: str


class FollowerOut(BaseModel):
    answer: str
    re_read_files: list[str] = []


def _mark(label: str) -> None:
    print(f"MARK {datetime.now(UTC).strftime('%H:%M:%S')} {label}", flush=True)


async def _get_warmup_env_id() -> str:
    def _ensure() -> str:
        team = Team.objects.get(id=TEAM_ID)
        user = User.objects.get(id=USER_ID)
        env, _created = SandboxEnvironment.objects.get_or_create(
            team=team,
            name="reviewhog-warmup-1h-ttl",
            defaults={
                "created_by": user,
                "network_access_level": SandboxEnvironment.NetworkAccessLevel.FULL,
                "environment_variables": {"ENABLE_PROMPT_CACHING_1H": "1"},
            },
        )
        return str(env.id)

    return await sync_to_async(_ensure)()


def _context(sandbox_environment_id: str | None = None) -> CustomPromptSandboxContext:
    return CustomPromptSandboxContext(
        team_id=TEAM_ID,
        user_id=USER_ID,
        repository=REPOSITORY,
        model=REVIEW_MODEL,
        runtime_adapter=REVIEW_RUNTIME_ADAPTER,
        reasoning_effort=REVIEW_REASONING_EFFORT,
        sandbox_environment_id=sandbox_environment_id,
    )


async def _wait_for_transcript_artifact(run_id: str, timeout_s: int = 300) -> str | None:
    def _check() -> str | None:
        run = TaskRun.objects.only("artifacts").get(id=run_id)
        for artifact in run.artifacts or []:
            name = artifact.get("name", "")
            if name.startswith("transcript-") and artifact.get("storage_path"):
                return name
        return None

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        name = await sync_to_async(_check)()
        if name:
            return name
        await asyncio.sleep(5)
    return None


async def _follower(label: str, resume_run_id: str, resume_task_id: str) -> None:
    _mark(f"{label} launching")
    session, parsed = await MultiTurnSession.start(
        prompt=FOLLOWER_PROMPT,
        context=_context(),
        model=FollowerOut,
        branch=BRANCH,
        step_name=f"spike2-follower-{label}",
        resume_from_run_id=resume_run_id,
        resume_from_task_id=resume_task_id,
    )
    try:
        _mark(f"{label} first turn done · task={session.task.id} run={session.task_run.id}")
        print(f"{label} answer: {parsed.answer[:200]}", flush=True)
        print(f"{label} re_read_files: {parsed.re_read_files}", flush=True)
    finally:
        await session.end()


async def main() -> None:
    env_id = await _get_warmup_env_id()
    print(f"warmup sandbox env (1h TTL): {env_id}", flush=True)

    _mark("A launching (warm-up)")
    session_a, warmup = await MultiTurnSession.start(
        prompt=WARMUP_PROMPT,
        context=_context(sandbox_environment_id=env_id),
        model=WarmUpOut,
        branch=BRANCH,
        step_name="spike2-warmup",
    )
    a_task_id = str(session_a.task.id)
    a_run_id = str(session_a.task_run.id)
    try:
        _mark(f"A first turn done · task={a_task_id} run={a_run_id} · files_read={len(warmup.files_read)}")

        settle = await session_a.send_followup(SETTLE_PROMPT, Ack, label="spike2-settle")
        _mark(f"A settling turn done · {settle.status}")
    finally:
        await session_a.end()
    _mark("A ended (transcript upload fires at cleanup)")

    artifact = await _wait_for_transcript_artifact(a_run_id)
    if not artifact:
        print("FAIL: no transcript artifact on A within 5min — check agent build / upload path", flush=True)
        return
    _mark(f"A transcript artifact visible: {artifact}")

    results = await asyncio.gather(
        _follower("B", a_run_id, a_task_id),
        _follower("C", a_run_id, a_task_id),
        return_exceptions=True,
    )
    for label, result in zip(["B", "C"], results):
        if isinstance(result, BaseException):
            print(f"{label} FAILED: {result}", flush=True)

    print(f"\nSPIKE2 IDS: warmup_task={a_task_id} warmup_run={a_run_id}", flush=True)
    print("Analyze with the $ai_generation SQL in PLAN.md M3 (fidelity + latency + no-rewrite-race).", flush=True)


asyncio.run(main())
