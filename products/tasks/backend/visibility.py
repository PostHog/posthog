"""Task visibility filters.

Kept out of the API module so import-light consumers (the file-system registration in
posthog.api.file_system.registrations, which loads at django.setup()) don't pull the whole
tasks API surface. Its module-scope imports reach jsonschema and the modal SDK.
"""

from typing import Literal

from django.db.models import Q

from products.tasks.backend.models import Channel, Task

TaskRelation = Literal["", "task"]

# These origins predate channels and remain team-scoped while their tasks have no channel.
# Once a task is filed into a channel, the channel is authoritative.
TEAM_VISIBLE_ORIGIN_PRODUCTS = [
    Task.OriginProduct.SIGNAL_REPORT,
    Task.OriginProduct.SIGNALS_SCOUT,
    Task.OriginProduct.ONBOARDING,
    Task.OriginProduct.HOGDESK,
]

TEAM_READABLE_ORIGIN_PRODUCTS = [
    *TEAM_VISIBLE_ORIGIN_PRODUCTS,
    Task.OriginProduct.EXPERIMENTS,
]


def _field(relation: TaskRelation, name: str) -> str:
    return f"{relation}__{name}" if relation else name


def _channel_relation(relation: TaskRelation) -> Literal["channel", "task__channel"]:
    return "task__channel" if relation == "task" else "channel"


def _creator_q(user_id: int | None, relation: TaskRelation) -> Q:
    if user_id is None:
        return Q(**{f"{_field(relation, 'pk')}__in": []})
    return Q(**{_field(relation, "created_by_id"): user_id})


def task_control_q(user_id: int | None, *, relation: TaskRelation = "") -> Q:
    """Tasks the user may mutate or drive.

    A task with a channel must be visible through that channel and owned by the user.
    Null-channel tasks keep the product-origin control rules used before channels.
    """
    channeled_q = (
        Q(**{f"{_field(relation, 'channel_id')}__isnull": False})
        & Channel.visible_to_q(user_id, relation=_channel_relation(relation))
        & _creator_q(user_id, relation)
    )
    legacy_q = Q(**{f"{_field(relation, 'channel_id')}__isnull": True}) & (
        _creator_q(user_id, relation) | Q(**{f"{_field(relation, 'origin_product')}__in": TEAM_VISIBLE_ORIGIN_PRODUCTS})
    )
    return channeled_q | legacy_q


def task_visibility_q(user_id: int | None, *, relation: TaskRelation = "") -> Q:
    """Tasks readable by the user.

    Channel visibility is authoritative when a task has a channel. The creator and
    product-origin fallback applies only to null-channel compatibility rows.
    """
    channeled_q = Q(**{f"{_field(relation, 'channel_id')}__isnull": False}) & Channel.visible_to_q(
        user_id, relation=_channel_relation(relation)
    )
    legacy_q = Q(**{f"{_field(relation, 'channel_id')}__isnull": True}) & (
        _creator_q(user_id, relation)
        | Q(**{f"{_field(relation, 'origin_product')}__in": TEAM_READABLE_ORIGIN_PRODUCTS})
    )
    return channeled_q | legacy_q


def task_run_visibility_q(user_id: int | None) -> Q:
    """``task_visibility_q`` traversed through the parent task relation."""
    return task_visibility_q(user_id, relation="task")
