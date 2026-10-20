import hashlib
from uuid import UUID

from django.db import transaction

from products.tasks.backend.models import Task
from products.tasks.backend.visibility import task_control_q

MOBILE_PUSH_USER_IDS = "mobile_push_user_ids"


def mobile_push_user_ids(task: Task) -> set[int]:
    values = (task.state or {}).get(MOBILE_PUSH_USER_IDS, [])
    return {value for value in values if type(value) is int} if isinstance(values, list) else set()


def task_mobile_push_eligible(task: Task, user_id: int) -> bool:
    return user_id in mobile_push_user_ids(task) or (
        (task.state or {}).get("created_on_mobile") is True and task.origin_product != Task.OriginProduct.SLACK
    )


def record_mobile_pickup(*, task_id: str | UUID, team_id: int, user_id: int) -> None:
    with transaction.atomic():
        task = (
            Task.objects.select_for_update(no_key=True, of=("self",))
            .filter(id=task_id, team_id=team_id, deleted=False)
            .filter(task_control_q(user_id))
            .first()
        )
        if task is None:
            return
        recipients = mobile_push_user_ids(task)
        if user_id in recipients:
            return
        task.state = {**(task.state or {}), MOBILE_PUSH_USER_IDS: sorted(recipients | {user_id})}
        task.save(update_fields=["state", "updated_at"])


def claim_mobile_pr_outcome(*, task_id: str | UUID, team_id: int, user_id: int, pr_url: str, kind: str) -> bool:
    event_id = f"{user_id}:{kind.removeprefix('report_')}:{hashlib.sha256(pr_url.encode()).hexdigest()}"
    with transaction.atomic():
        task = Task.objects.select_for_update(no_key=True).only("id", "state").get(id=task_id, team_id=team_id)
        state = dict(task.state or {})
        outcomes = state.get("mobile_push_pr_outcomes", [])
        outcomes = outcomes if isinstance(outcomes, list) else []
        if event_id in outcomes:
            return False
        task.state = {**state, "mobile_push_pr_outcomes": [*outcomes, event_id]}
        task.save(update_fields=["state", "updated_at"])
    return True
