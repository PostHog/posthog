"""Task visibility filters.

Kept out of the API module so import-light consumers (the file-system registration in
posthog.api.file_system.registrations, which loads at django.setup()) don't pull the whole
tasks API surface. Its module-scope imports reach jsonschema and the modal SDK.
"""

from django.db.models import Q

from products.tasks.backend.facade.profiles import DrivePolicy, Read, origins_where
from products.tasks.backend.models import Channel, Task


# These origins predate channels and remain team-scoped while their tasks have no channel.
# Once a task is filed into a channel, the channel is authoritative.
def _team_visible_origins() -> list[str]:
    return sorted(origins_where(drive=DrivePolicy.AUDIENCE))


def _team_readable_origins() -> list[str]:
    return sorted(origins_where(read_without_channel=Read.TEAM))


# These tasks carry another product's data, so only that product reads them, through its own facade
# and scopes. Sandbox callers bypass these filters, so the run itself still works.
def _product_private_origins() -> list[str]:
    return sorted(origins_where(api_visible=False))


def _creator_q(user_id: int | None) -> Q:
    return Q(pk__in=[]) if user_id is None else Q(created_by_id=user_id)


def scout_trial_visibility_q(user_id: int | None) -> Q:
    return ~Task.scout_experiment_q() | _creator_q(user_id)


def task_control_q(user_id: int | None) -> Q:
    """Tasks the user may mutate or drive.

    A task with a channel must be visible through that channel and owned by the user.
    Null-channel tasks keep the product-origin control rules used before channels.
    """
    channeled_q = Q(channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="channel") & _creator_q(user_id)
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=_team_visible_origins())
    )
    return (
        (channeled_q | legacy_q) & scout_trial_visibility_q(user_id) & ~Q(origin_product__in=_product_private_origins())
    )


def task_visibility_q(user_id: int | None) -> Q:
    """Tasks readable by the user.

    Channel visibility is authoritative when a task has a channel. The creator and
    product-origin fallback applies only to null-channel compatibility rows.
    """
    channeled_q = Q(channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="channel")
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=_team_readable_origins())
    )
    return (
        (channeled_q | legacy_q) & scout_trial_visibility_q(user_id) & ~Q(origin_product__in=_product_private_origins())
    )


def task_run_visibility_q(user_id: int | None) -> Q:
    """``task_visibility_q`` traversed through the parent task relation."""
    channeled_q = Q(task__channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="task__channel")
    legacy_q = Q(task__channel_id__isnull=True) & (
        (Q(task__pk__in=[]) if user_id is None else Q(task__created_by_id=user_id))
        | Q(task__created_by__isnull=True)
        | Q(task__origin_product__in=_team_readable_origins())
    )
    trial_visibility = ~Task.scout_experiment_q(relation="task")
    if user_id is not None:
        trial_visibility |= Q(task__created_by_id=user_id)
    return (channeled_q | legacy_q) & trial_visibility & ~Q(task__origin_product__in=_product_private_origins())
