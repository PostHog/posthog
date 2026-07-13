"""Driver for a full eval run. Invoked inside Django:

    DEBUG=1 python manage.py shell -c "
    from products.signals.eval.self_driving.harness.drive import drive
    drive(trials=1, parallelism=2)"

Prerequisites (checked/failed fast where visible from this process):
- Temporal worker running with SANDBOX_REPO_MOUNT_MAP covering every task repo
  (print_mount_map() emits the correct value for the current task set)
- MCP dev server on :8787, Django on :8000, ClickHouse, Temporal, personhog
"""

import os
import json
import time
import asyncio
from pathlib import Path
from typing import Any

from products.signals.eval.self_driving.harness import runner as runner_mod

DEFAULT_WORKSPACE = Path(
    os.environ.get(
        "SELFDRIVING_EVAL_WORKSPACE",
        "/tmp/selfdriving-eval-workspace",
    )
)


def all_task_ids() -> list[str]:
    return sorted(p.name for p in runner_mod.TASKS_DIR.iterdir() if (p / "task.json").exists())


def print_mount_map(task_ids: list[str] | None = None, workspace: Path = DEFAULT_WORKSPACE) -> str:
    ids = task_ids or all_task_ids()
    mm = runner_mod.build_mount_map(ids, workspace)
    print(mm)
    return mm


def _check_prereqs(task_ids: list[str]) -> None:
    import urllib.request

    for url, name in [("http://localhost:8787/mcp", "mcp dev server"), ("http://localhost:8000/_health", "django")]:
        try:
            urllib.request.urlopen(url, timeout=5)
        except Exception as e:
            code = getattr(e, "code", None)
            if code is None:
                raise RuntimeError(f"prereq {name} unreachable at {url}: {e}")


def drive(
    task_ids: list[str] | None = None,
    trials: int = 1,
    parallelism: int = 2,
    workspace: str | Path = DEFAULT_WORKSPACE,
    research_timeout_s: float = 3600,
    implementation_timeout_s: float = 2700,
    experiment_name: str | None = None,
) -> Any:
    from products.signals.eval.self_driving.eval_selfdriving import run_eval

    ws = Path(workspace)
    ids = task_ids or all_task_ids()
    _check_prereqs(ids)
    (ws / "results").mkdir(parents=True, exist_ok=True)
    exp_name = experiment_name or f"selfdriving-{time.strftime('%Y%m%d-%H%M')}"

    async def run_fn(task_id: str, trial: int) -> dict[str, Any]:
        print(f"[{time.strftime('%H:%M:%S')}] starting {task_id} trial {trial}", flush=True)
        res = await runner_mod.run_one_task(
            task_id,
            ws,
            trial=trial,
            research_timeout_s=research_timeout_s,
            implementation_timeout_s=implementation_timeout_s,
        )
        out = res.to_json()
        (ws / "results" / f"{task_id}-t{trial}.json").write_text(json.dumps(out, indent=1, default=str))
        report = out.get("report") or {}
        impl = out.get("implementation_run") or {}
        print(
            f"[{time.strftime('%H:%M:%S')}] finished {task_id} trial {trial}: "
            f"report={report.get('status')} impl={impl.get('status')} "
            f"patch_bytes={len(out.get('patch') or '')} failure={out.get('failure')}",
            flush=True,
        )
        return out

    return asyncio.run(
        run_eval(
            ids,
            trials,
            ws,
            exp_name,
            run_fn,
            max_concurrency=parallelism,
        )
    )
