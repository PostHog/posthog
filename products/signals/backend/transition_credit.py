"""The person a report status transition names in analytics, and why that person.

`signal_report_status_changed` is sent as this person, so a count of distinct people over the
event counts the people behind the transitions. The source lets a reader leave out a person the
system picked, such as the creator of an auto-started task, who may never have acted on the report.
"""

from __future__ import annotations

from typing import Literal

from posthog.dataclasses import frozen
from posthog.models.user import User

from products.signals.backend.artefact_attribution import ArtefactAttribution

CreditSource = Literal["request", "claim", "pr_attacher", "pr_merger", "task_creator"]


@frozen
class TransitionCredit:
    user: User
    source: CreditSource


def _user(user_id: int, loaded: User | None) -> User | None:
    # The bulk-state endpoint transitions up to 100 reports in one request, so it passes the request
    # user to skip a repeat lookup per report.
    return loaded if loaded is not None and loaded.id == user_id else User.objects.filter(id=user_id).first()


def resolve_transition_credit(
    actor: ArtefactAttribution | None,
    credit: TransitionCredit | None,
    *,
    team_id: int,
    actor_user: User | None = None,
) -> TransitionCredit | None:
    """The person to name for a transition that `actor` made, or None when nobody stands behind it.

    A person who made the call names themselves. Otherwise the credit the caller worked out
    applies, and a task with no such credit names the person who started it.
    """
    if actor is not None and actor.user_id is not None:
        user = _user(actor.user_id, actor_user)
        return TransitionCredit(user=user, source="request") if user is not None else None
    if credit is not None:
        return credit
    if actor is None or actor.task_id is None:
        return None
    from products.tasks.backend.facade import (  # noqa: PLC0415 - the receivers import this module at django.setup(), where the startup import budget forbids the tasks facade
        api as tasks_facade,
    )

    creator_id = tasks_facade.get_task_creator_ids([actor.task_id], [team_id]).get(actor.task_id)
    # The task id on a request is caller-supplied, so a task names its creator only when the creator
    # made the request. Otherwise a caller could credit another person by naming that person's task.
    if creator_id is None or actor.request_user_id not in (None, creator_id):
        return None
    creator = _user(creator_id, actor_user)
    return TransitionCredit(user=creator, source="task_creator") if creator is not None else None
