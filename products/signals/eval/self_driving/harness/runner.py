"""Orchestrates one eval task through the REAL self-driving pipeline.

For each task (see TASK_SPEC.md):
1. provision an isolated team (provision.py)
2. materialize the fixture repo into the run workspace and git-init it
3. seed ClickHouse product telemetry (seed.py)
4. emit the task's signals through the real emission pipeline
5. wait for the SignalReport to reach a terminal research state
6. wait for the auto-started implementation task run to finish
7. collect everything gradeable: report + artefacts, the repo diff, run logs

The runner is imported inside Django (`DEBUG=1 python manage.py shell`), with the
Temporal worker running separately with SANDBOX_REPO_MOUNT_MAP covering every task repo.
"""

import json
import time
import shutil
import asyncio
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"
REPO_ORG = "acme"

RESEARCH_TERMINAL = {"ready", "pending_input", "failed", "dismissed"}
TASK_RUN_TERMINAL = {"completed", "failed", "cancelled"}

# Local ClickHouse allows only one unfinished mutation per table — the cleanup deletes
# (cleanup_signals + clear_task_events) from concurrent tasks must not overlap.
_SETUP_LOCK = asyncio.Lock()


@dataclass
class TaskRunResult:
    task_id: str
    team_id: int = 0
    trial: int = 0
    report: dict[str, Any] | None = None
    artefacts: list[dict[str, Any]] = field(default_factory=list)
    implementation_run: dict[str, Any] | None = None
    patch: str = ""
    commit_messages: list[str] = field(default_factory=list)
    seeded_counts: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)
    failure: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "team_id": self.team_id,
            "trial": self.trial,
            "report": self.report,
            "artefacts": self.artefacts,
            "implementation_run": self.implementation_run,
            "patch": self.patch,
            "commit_messages": self.commit_messages,
            "seeded_counts": self.seeded_counts,
            "timings": self.timings,
            "failure": self.failure,
        }


def load_task_spec(task_id: str) -> dict[str, Any]:
    return json.loads((TASKS_DIR / task_id / "task.json").read_text())


def repo_full_name(task_id: str) -> str:
    return f"{REPO_ORG}/{task_id}"


def build_mount_map(task_ids: list[str], workspace: Path) -> str:
    return ",".join(f"{repo_full_name(t)}:{workspace / 'repos' / t}" for t in task_ids)


def materialize_repo(task_id: str, workspace: Path) -> Path:
    """Copy the task's template repo into the workspace and create a plausible git history."""
    src = TASKS_DIR / task_id / "repo"
    dst = workspace / "repos" / task_id
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    env_author = {
        "GIT_AUTHOR_NAME": "dana-acme",
        "GIT_AUTHOR_EMAIL": "dana@acme.test",
        "GIT_COMMITTER_NAME": "dana-acme",
        "GIT_COMMITTER_EMAIL": "dana@acme.test",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(dst), *args], check=True, capture_output=True, env={**env_author})

    subprocess.run(["git", "init", "-q", "-b", "main", str(dst)], check=True, capture_output=True)
    git("add", "-A")
    git("commit", "-qm", "feat: initial service implementation")
    # A couple of innocent commits so the defect isn't trivially "the last change".
    readme = dst / "README.md"
    if readme.exists():
        readme.write_text(readme.read_text() + "\n<!-- ops: deployed 2026-07-08 -->\n")
        git("add", "-A")
        git("commit", "-qm", "docs: note deployment date")
    (dst / ".editorconfig").write_text("root = true\n\n[*]\nindent_style = space\nindent_size = 2\n")
    git("add", "-A")
    git("commit", "-qm", "chore: add editorconfig")

    # A local bare "origin" so the agent's push works without GitHub.
    bare = workspace / "remotes" / f"{task_id}.git"
    if bare.exists():
        shutil.rmtree(bare)
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
    git("remote", "add", "origin", str(bare))
    git("push", "-q", "origin", "main")
    return dst


def manage(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    """Run a manage.py command in a subprocess (fresh env, .env sourced by caller's shell)."""
    import django.conf

    base_dir = Path(django.conf.settings.BASE_DIR)
    return subprocess.run(
        ["python", "manage.py", *args],
        cwd=base_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _report_rows(team_id: int) -> list[dict[str, Any]]:
    from products.signals.backend.models import SignalReport

    return [
        {
            "id": str(r.id),
            "status": r.status,
            "title": r.title,
            "summary": r.summary,
            "priority": getattr(r, "priority", None),
            "created_at": r.created_at.isoformat(),
        }
        for r in SignalReport.objects.filter(team_id=team_id).order_by("created_at")
    ]


def _artefact_rows(report_id: str) -> list[dict[str, Any]]:
    from products.signals.backend.models import SignalReportArtefact

    return [
        {
            "type": a.type,
            "content": a.content,
            "created_at": a.created_at.isoformat(),
        }
        for a in SignalReportArtefact.objects.filter(report_id=report_id).order_by("created_at")
    ]


def _implementation_runs(team_id: int) -> list[dict[str, Any]]:
    from products.tasks.backend.models import Task, TaskRun

    runs = []
    for tr in TaskRun.objects.filter(task__team_id=team_id).order_by("created_at"):
        task: Task = tr.task
        runs.append(
            {
                "task_id": str(task.id),
                "run_id": str(tr.id),
                "status": tr.status,
                "error_message": tr.error_message,
                "log_url": tr.log_url,
                "title": task.title,
                "repository": task.repository,
                "origin_product": task.origin_product,
                "created_at": tr.created_at.isoformat(),
            }
        )
    return runs


def read_run_log_tail(log_url: str | None, tail_chars: int = 20000) -> str:
    if not log_url:
        return ""
    from posthog.storage import object_storage

    content = object_storage.read(log_url, missing_ok=True) or ""
    return content[-tail_chars:]


def extract_patch(repo_dir: Path) -> tuple[str, list[str]]:
    """Diff of everything the agent did on top of the harness's base commits."""

    def git(*args: str) -> str:
        out = subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, text=True)
        return out.stdout

    base = git("rev-list", "--max-count=1", "--grep=chore: add editorconfig", "--all").strip().splitlines()
    base_sha = base[0] if base else git("rev-list", "--max-parents=0", "HEAD").strip().splitlines()[0]
    # The agent may commit on a feature branch without checking main out again —
    # grade the newest tip across all local branches.
    tips = [
        line.split()
        for line in git(
            "for-each-ref", "--sort=-committerdate", "--format=%(objectname) %(refname:short)", "refs/heads"
        ).splitlines()
    ]
    head = tips[0][0] if tips else "HEAD"
    messages = [m for m in git("log", "--format=%s", f"{base_sha}..{head}").splitlines() if m]
    committed = git("diff", base_sha, head)
    uncommitted = git("diff", "HEAD")
    untracked_names = [n for n in git("ls-files", "--others", "--exclude-standard").splitlines() if n]
    untracked_blobs = []
    for name in untracked_names[:50]:
        p = repo_dir / name
        if p.is_file() and p.stat().st_size < 100_000:
            untracked_blobs.append(f"--- /dev/null\n+++ b/{name}\n{p.read_text(errors='replace')}")
    patch = committed + ("\n" + uncommitted if uncommitted.strip() else "")
    if untracked_blobs:
        patch += "\n# untracked files created by agent:\n" + "\n".join(untracked_blobs)
    return patch, messages


async def wait_for(predicate, timeout_s: float, poll_s: float = 20.0, desc: str = ""):
    from asgiref.sync import sync_to_async

    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        result = await sync_to_async(predicate, thread_sensitive=False)()
        if result is not None:
            return result
        await asyncio.sleep(poll_s)
    raise TimeoutError(f"timed out after {timeout_s}s waiting for {desc}")


async def run_one_task(
    task_id: str,
    workspace: Path,
    trial: int = 0,
    research_timeout_s: float = 3600,
    implementation_timeout_s: float = 3600,
) -> TaskRunResult:
    from asgiref.sync import sync_to_async

    from products.signals.eval.self_driving.harness.provision import provision_task_team
    from products.signals.eval.self_driving.harness.seed import clear_task_events, seed_task_events

    spec = load_task_spec(task_id)
    result = TaskRunResult(task_id=task_id, trial=trial)
    t0 = time.monotonic()

    try:
        repo_dir = materialize_repo(task_id, workspace)
        info = await sync_to_async(provision_task_team, thread_sensitive=False)(
            task_id, repo_full_name(task_id), str(repo_dir)
        )
        result.team_id = team_id = info["team_id"]

        # Clean slate: previous trials' reports/signals/embeddings and seeded events.
        # Serialized across tasks — concurrent ClickHouse mutations exceed the local limit.
        async with _SETUP_LOCK:
            cleanup = await asyncio.to_thread(manage, ["cleanup_signals", "--team-id", str(team_id), "--yes"])
            if cleanup.returncode != 0:
                raise RuntimeError(f"cleanup_signals failed: {cleanup.stderr[-500:]}")
            await sync_to_async(clear_task_events, thread_sensitive=False)(team_id)
            result.timings["setup"] = time.monotonic() - t0

            seeded = await sync_to_async(seed_task_events, thread_sensitive=False)(team_id, spec["seed"])
            result.seeded_counts = seeded
            result.timings["seed"] = time.monotonic() - t0

        emit = await asyncio.to_thread(
            manage,
            [
                "emit_signals_from_fixture",
                "--type",
                spec["signal_type"],
                "--team-id",
                str(team_id),
                "--fixture",
                str(TASKS_DIR / task_id / "signals.json"),
            ],
        )
        if "signals_emitted" not in emit.stdout + emit.stderr:
            raise RuntimeError(f"emission failed: {(emit.stdout + emit.stderr)[-800:]}")
        result.timings["emit"] = time.monotonic() - t0

        def research_done():
            rows = _report_rows(team_id)
            terminal = [r for r in rows if r["status"] in RESEARCH_TERMINAL]
            return terminal[0] if terminal else None

        report = await wait_for(research_done, research_timeout_s, desc=f"{task_id} research")
        result.report = report
        result.artefacts = await sync_to_async(_artefact_rows, thread_sensitive=False)(report["id"])
        result.timings["research"] = time.monotonic() - t0

        def implementation_done():
            runs = _implementation_runs(team_id)
            if not runs:
                return None
            latest = runs[-1]
            return latest if latest["status"] in TASK_RUN_TERMINAL else None

        impl = None
        if report["status"] == "ready":
            try:
                impl = await wait_for(implementation_done, implementation_timeout_s, desc=f"{task_id} implementation")
            except TimeoutError:
                impl = None
        if impl is not None:
            impl["log_tail"] = await sync_to_async(read_run_log_tail, thread_sensitive=False)(impl.get("log_url"))
        result.implementation_run = impl
        result.timings["implementation"] = time.monotonic() - t0

        result.patch, result.commit_messages = extract_patch(repo_dir)
    except Exception as e:  # noqa: BLE001 — the eval must record, not crash
        result.failure = f"{type(e).__name__}: {e}"

    result.timings["total"] = time.monotonic() - t0
    return result
