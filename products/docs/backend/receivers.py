"""Signal receivers. Connected in ``apps.py``; the facade does the work."""

from typing import Any

from products.docs.backend.facade import api


def on_task_run_turn_finished(
    sender: Any, *, task_run: Any, text: str, turn_key: str, last_text: str | None = None, **kwargs: Any
) -> None:
    api.record_agent_turn(
        team_id=task_run.team_id,
        task_id=str(task_run.task_id),
        run_id=str(task_run.id),
        turn_key=turn_key,
        text=last_text or text,
        loop_id=str(task_run.task.loop_id) if getattr(task_run.task, "loop_id", None) else None,
    )
