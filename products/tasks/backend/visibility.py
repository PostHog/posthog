"""Task visibility filters.

Kept out of the API module so import-light consumers (the file-system registration in
posthog.api.file_system.registrations, which loads at django.setup()) don't pull the whole
tasks API surface. Its module-scope imports reach jsonschema and the modal SDK.
"""

from django.db.models import Exists, OuterRef, Q

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


def _creator_q(user_id: int | None) -> Q:
    return Q(pk__in=[]) if user_id is None else Q(created_by_id=user_id)


def task_control_q(user_id: int | None) -> Q:
    """Tasks the user may mutate or drive.

    A task with a channel must be visible through that channel and owned by the user.
    Null-channel tasks keep the product-origin control rules used before channels.
    """
    channeled_q = Q(channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="channel") & _creator_q(user_id)
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=TEAM_VISIBLE_ORIGIN_PRODUCTS)
    )
    return channeled_q | legacy_q


def task_visibility_q(user_id: int | None) -> Q:
    """Tasks readable by the user.

    Channel visibility is authoritative when a task has a channel. The creator and
    product-origin fallback applies only to null-channel compatibility rows.
    """
    channeled_q = Q(channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="channel")
    legacy_q = Q(channel_id__isnull=True) & (
        _creator_q(user_id) | Q(created_by__isnull=True) | Q(origin_product__in=TEAM_READABLE_ORIGIN_PRODUCTS)
    )
    return channeled_q | legacy_q


def shared_slack_thread_q() -> Q:
    """Slack tasks whose thread is not a direct message.

    Phrased as "not private" rather than "is a channel" so a mapping we never classified — a
    row predating the column, or a lookup Slack refused — keeps the team-wide read access it
    has today instead of silently narrowing to the thread starter.

    The ``origin_product`` test leads so the subquery is only reached for Slack tasks; every
    other task short-circuits on an indexed column before touching the mapping table.
    """
    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off this module's import path
        PRIVATE_CONVERSATION_TYPES,
        SlackThreadTaskMapping,
    )

    private_thread = SlackThreadTaskMapping.objects.filter(
        task_id=OuterRef("pk"),
        conversation_type__in=sorted(PRIVATE_CONVERSATION_TYPES),
    )
    return Q(origin_product=Task.OriginProduct.SLACK) & Q(~Exists(private_thread))


def task_read_visibility_q(user_id: int | None) -> Q:
    """The whole rule the Task API reads with: channel visibility, plus a Slack task whose
    thread is not a direct message, which stays readable team-wide however it is filed.

    Every surface that mirrors Task read access uses this, not ``task_visibility_q`` alone.
    A Slack task lands in the thread starter's personal channel, so the narrower predicate
    calls it hidden while the API hands it to any teammate.
    """
    return task_visibility_q(user_id) | shared_slack_thread_q()


def task_run_visibility_q(user_id: int | None) -> Q:
    """``task_visibility_q`` traversed through the parent task relation."""
    channeled_q = Q(task__channel_id__isnull=False) & Channel.visible_to_q(user_id, relation="task__channel")
    legacy_q = Q(task__channel_id__isnull=True) & (
        (Q(task__pk__in=[]) if user_id is None else Q(task__created_by_id=user_id))
        | Q(task__created_by__isnull=True)
        | Q(task__origin_product__in=TEAM_READABLE_ORIGIN_PRODUCTS)
    )
    return channeled_q | legacy_q
