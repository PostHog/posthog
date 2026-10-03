"""Task visibility filters.

Kept out of the API module so import-light consumers (the file-system registration in
posthog.api.file_system.registrations, which loads at django.setup()) don't pull the whole
tasks API surface. Its module-scope imports reach jsonschema and the modal SDK.
"""

from django.db.models import Q, Subquery
from django.db.models.functions import Coalesce

from posthog.models.team import Team

from products.tasks.backend.models import Channel, Task

# These origins predate channels and remain team-scoped while their tasks have no channel.
# Once a task is filed into a channel, the channel is authoritative.
TEAM_VISIBLE_ORIGIN_PRODUCTS = [
    Task.OriginProduct.SIGNAL_REPORT,
    Task.OriginProduct.SIGNALS_SCOUT,
    Task.OriginProduct.ONBOARDING,
    Task.OriginProduct.HOGDESK,
    # A shared workflow's tasks are the team's: anyone can jump in and continue one. The
    # sandbox still runs under the credentials minted for the workflow's owner.
    Task.OriginProduct.WORKFLOW,
]

TEAM_READABLE_ORIGIN_PRODUCTS = [
    *TEAM_VISIBLE_ORIGIN_PRODUCTS,
    Task.OriginProduct.EXPERIMENTS,
]

# These tasks carry another product's data, so only that product reads them, through its own facade
# and scopes. Sandbox callers bypass these filters, so the run itself still works.
PRODUCT_PRIVATE_ORIGIN_PRODUCTS = [
    Task.OriginProduct.BUSINESS_KNOWLEDGE,
]


def _creator_q(user_id: int | None) -> Q:
    return Q(pk__in=[]) if user_id is None else Q(created_by_id=user_id)


def _channeled_q(user_id: int | None, team_id: int | None) -> Q:
    if team_id is None:
        return Q(channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="channel")
    # Joined channel columns inside the OR make Postgres scan the channel and membership tables
    # of every team. A team-scoped subquery runs once and reads only this team's channels.
    # Channels live on the parent team, so a child environment resolves to its parent.
    canonical_team_id = Team.objects.filter(id=team_id).values(canonical_id=Coalesce("parent_team_id", "id"))[:1]
    visible_channel_ids = (
        Channel.objects.unscoped()
        .filter(Channel.visible_to_q(user_id), team_id=Subquery(canonical_team_id))
        .values("id")
    )
    return Q(channel_id__in=visible_channel_ids)


def task_control_q(user_id: int | None, *, team_id: int | None = None) -> Q:
    """Tasks the user may mutate or drive.

    A task with a channel must be visible through that channel and owned by the user.
    Null-channel tasks keep the product-origin control rules used before channels.
    Pass ``team_id`` when the queryset is filtered to that team, so the channel check stays in the team.
    """
    channeled_q = _channeled_q(user_id, team_id) & _creator_q(user_id)
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=TEAM_VISIBLE_ORIGIN_PRODUCTS)
    )
    return (channeled_q | legacy_q) & ~Q(origin_product__in=PRODUCT_PRIVATE_ORIGIN_PRODUCTS)


def task_visibility_q(user_id: int | None, *, team_id: int | None = None) -> Q:
    """Tasks readable by the user.

    Channel visibility is authoritative when a task has a channel. The creator and
    product-origin fallback applies only to null-channel compatibility rows.
    Pass ``team_id`` when the queryset is filtered to that team, so the channel check stays in the team.
    """
    channeled_q = _channeled_q(user_id, team_id)
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=TEAM_READABLE_ORIGIN_PRODUCTS)
    )
    return (channeled_q | legacy_q) & ~Q(origin_product__in=PRODUCT_PRIVATE_ORIGIN_PRODUCTS)


def task_run_visibility_q(user_id: int | None) -> Q:
    """``task_visibility_q`` traversed through the parent task relation."""
    channeled_q = Q(task__channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="task__channel")
    legacy_q = Q(task__channel_id__isnull=True) & (
        (Q(task__pk__in=[]) if user_id is None else Q(task__created_by_id=user_id))
        | Q(task__created_by__isnull=True)
        | Q(task__origin_product__in=TEAM_READABLE_ORIGIN_PRODUCTS)
    )
    return (channeled_q | legacy_q) & ~Q(task__origin_product__in=PRODUCT_PRIVATE_ORIGIN_PRODUCTS)
