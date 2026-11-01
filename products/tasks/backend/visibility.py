"""Task visibility filters.

Kept out of the API module so import-light consumers (the file-system registration in
posthog.api.file_system.registrations, which loads at django.setup()) don't pull the whole
tasks API surface. Its module-scope imports reach jsonschema and the modal SDK.
"""

from typing import cast

from django.db.models import BooleanField, OuterRef, Q, Subquery, Value
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
    Task.OriginProduct.ACCOUNT_AUDIT,
    Task.OriginProduct.METRICS_IMPORT,
]


def _creator_q(user_id: int | None) -> Q:
    return Q(pk__in=[]) if user_id is None else Q(created_by_id=user_id)


def _visible_channel_q(user_id: int | OuterRef | None, team_id: int | None, *, through_task: bool = False) -> Q:
    channel_user_id = cast(int, OuterRef(user_id)) if isinstance(user_id, OuterRef) else user_id
    channels = Channel.objects.unscoped().filter(Channel.visible_to_q(channel_user_id))
    if team_id is not None:
        root_team_id = Subquery(Team.objects.filter(id=team_id).values("parent_team_id")[:1])
        channel_ids = channels.filter(Q(team_id=team_id) | Q(team_id=root_team_id)).values("id")
        return Q(task__channel_id__in=channel_ids) if through_task else Q(channel_id__in=channel_ids)
    channel_ref = OuterRef("task__channel_id") if through_task else OuterRef("channel_id")
    visible_channel = channels.filter(pk=channel_ref).annotate(visible=Value(True)).values("visible")[:1]
    return Q(Coalesce(Subquery(visible_channel), Value(False), output_field=BooleanField()))


def scout_trial_visibility_q(user_id: int | None) -> Q:
    return ~Task.scout_experiment_q() | _creator_q(user_id)


def task_control_q(user_id: int | None, team_id: int | None = None) -> Q:
    """Tasks the user may mutate or drive.

    A task with a channel must be visible through that channel and owned by the user.
    Null-channel tasks keep the product-origin control rules used before channels.
    """
    channeled_q = Q(channel_id__isnull=False) & _visible_channel_q(user_id, team_id) & _creator_q(user_id)
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=TEAM_VISIBLE_ORIGIN_PRODUCTS)
    )
    return (
        (channeled_q | legacy_q)
        & scout_trial_visibility_q(user_id)
        & ~Q(origin_product__in=PRODUCT_PRIVATE_ORIGIN_PRODUCTS)
    )


def task_visibility_q(user_id: int | None, team_id: int | None = None) -> Q:
    """Tasks readable by the user.

    Channel visibility is authoritative when a task has a channel. The creator and
    product-origin fallback applies only to null-channel compatibility rows.
    """
    channeled_q = Q(channel_id__isnull=False) & _visible_channel_q(user_id, team_id)
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=TEAM_READABLE_ORIGIN_PRODUCTS)
    )
    return (
        (channeled_q | legacy_q)
        & scout_trial_visibility_q(user_id)
        & ~Q(origin_product__in=PRODUCT_PRIVATE_ORIGIN_PRODUCTS)
    )


def task_run_visibility_q(user_id: int | None, team_id: int | None = None) -> Q:
    """``task_visibility_q`` traversed through the parent task relation."""
    channeled_q = Q(task__channel_id__isnull=False) & _visible_channel_q(user_id, team_id, through_task=True)
    legacy_q = Q(task__channel_id__isnull=True) & (
        (Q(task__pk__in=[]) if user_id is None else Q(task__created_by_id=user_id))
        | Q(task__created_by__isnull=True)
        | Q(task__origin_product__in=TEAM_READABLE_ORIGIN_PRODUCTS)
    )
    trial_visibility = ~Task.scout_experiment_q(relation="task")
    if user_id is not None:
        trial_visibility |= Q(task__created_by_id=user_id)
    return (channeled_q | legacy_q) & trial_visibility & ~Q(task__origin_product__in=PRODUCT_PRIVATE_ORIGIN_PRODUCTS)
