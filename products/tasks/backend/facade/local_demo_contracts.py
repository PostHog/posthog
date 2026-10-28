from uuid import NAMESPACE_URL, uuid5

from posthog.dataclasses import frozen


@frozen
class LocalDemoTask:
    task_id: str
    run_id: str


def local_demo_task_ids(*, team_id: int, user_id: int) -> LocalDemoTask:
    task_id = uuid5(NAMESPACE_URL, f"posthog:local-inbox-demo:v1:{team_id}:{user_id}:chat")
    return LocalDemoTask(task_id=str(task_id), run_id=str(uuid5(task_id, "completed-run")))
