import hashlib
from collections.abc import Callable
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.user_push_token import UserPushToken

from products.tasks.backend.models import Task, TaskPresence
from products.tasks.backend.visibility import task_control_q

MOBILE_PUSH_USER_IDS = "mobile_push_user_ids"


def mobile_push_user_ids(task: Task) -> set[int]:
    values = (task.state or {}).get(MOBILE_PUSH_USER_IDS, [])
    return {value for value in values if type(value) is int} if isinstance(values, list) else set()


def task_mobile_push_eligible(task: Task, user_id: int) -> bool:
    return user_id in mobile_push_user_ids(task) or (
        (task.state or {}).get("created_on_mobile") is True and task.origin_product != Task.OriginProduct.SLACK
    )


def suppressed_push_token_ids_for_task(*, user_id: int, task_id: str | UUID, team_id: int) -> list[str]:
    """Return all of the user's UserPushToken UUIDs (as strings) when at least one device
    has beaconed presence for this task, otherwise an empty list.

    The contract documented on the beacon endpoint is "if any device is
    provably watching, suppress the others". The watching device doesn't need
    a push either because it already renders the task UI in real time, so when
    any presence row is active we suppress the entire fanout for the user.
    Computed at enqueue time; the Celery dispatch is essentially instant so
    the race window against the 30-second beacon cadence is irrelevant.
    """
    has_active_presence = (
        TaskPresence.objects.for_team(team_id)
        .filter(task_id=task_id, user_id=user_id, expires_at__gt=timezone.now())
        .exists()
    )
    if not has_active_presence:
        return []
    return [str(pid) for pid in UserPushToken.objects.filter(user_id=user_id).values_list("id", flat=True)]


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


def _mobile_pr_outcome_event_id(user_id: int, kind: str, pr_url: str) -> str:
    return f"{user_id}:{kind.removeprefix('report_')}:{hashlib.sha256(pr_url.encode()).hexdigest()}"


def _release_mobile_pr_outcome(*, task_id: str | UUID, team_id: int, event_id: str) -> None:
    with transaction.atomic():
        task = Task.objects.select_for_update(no_key=True).only("id", "state").get(id=task_id, team_id=team_id)
        state = dict(task.state or {})
        outcomes = state.get("mobile_push_pr_outcomes", [])
        task.state = {**state, "mobile_push_pr_outcomes": [value for value in outcomes if value != event_id]}
        task.save(update_fields=["state", "updated_at"])


def claim_mobile_pr_outcome(*, task_id: str | UUID, team_id: int, user_id: int, pr_url: str, kind: str) -> bool:
    event_id = _mobile_pr_outcome_event_id(user_id, kind, pr_url)
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


def enqueue_mobile_pr_outcome(
    *, task_id: str | UUID, team_id: int, user_id: int, pr_url: str, kind: str, enqueue: Callable[[], None]
) -> bool:
    if not claim_mobile_pr_outcome(task_id=task_id, team_id=team_id, user_id=user_id, pr_url=pr_url, kind=kind):
        return False
    try:
        enqueue()
    except Exception:
        _release_mobile_pr_outcome(
            task_id=task_id, team_id=team_id, event_id=_mobile_pr_outcome_event_id(user_id, kind, pr_url)
        )
        raise
    return True
