"""Facade API for logs.

The data-capability surface other apps import from. Functions accept and return
contracts, not ORM instances — the one exception is the ``*_queryset`` helpers, which
return a lazy QuerySet so the product's own list views can paginate at the DB; pair
them with the matching ``map_*`` mapper to convert a page into contracts.

Keep heavy imports (HogQL, temporalio) out of this module — those live in
``facade/queries.py`` and ``facade/temporal.py`` so config-only consumers don't drag
them onto the ``django.setup()`` import path.
"""

from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.db.models import QuerySet

from posthog.models.team.extensions import get_or_create_team_extension

from products.logs.backend.facade import contracts
from products.logs.backend.models import LogsView, TeamLogsConfig

if TYPE_CHECKING:
    from posthog.models import Team, User


def _to_team_logs_config(config: TeamLogsConfig) -> contracts.TeamLogsConfig:
    return contracts.TeamLogsConfig(logs_distinct_id_attribute_key=config.logs_distinct_id_attribute_key)


def get_team_logs_config(team: "Team") -> contracts.TeamLogsConfig:
    """Read a team's logs config, creating it with defaults if it doesn't exist yet."""
    config = get_or_create_team_extension(team, TeamLogsConfig)
    return _to_team_logs_config(config)


def update_team_logs_config(team: "Team", logs_distinct_id_attribute_key: str) -> contracts.TeamLogsConfig:
    """Set the distinct-id attribute key for a team's logs config."""
    config = get_or_create_team_extension(team, TeamLogsConfig)
    config.logs_distinct_id_attribute_key = logs_distinct_id_attribute_key
    config.save(update_fields=["logs_distinct_id_attribute_key"])
    return _to_team_logs_config(config)


# --- Saved views ---


class LogsViewNotFoundError(Exception):
    """Raised when a saved view doesn't exist for the given team."""


def _to_user_basic_info(user: "User | None") -> contracts.LogsUserBasicInfo | None:
    if user is None:
        return None
    return contracts.LogsUserBasicInfo(id=user.id, first_name=user.first_name, email=user.email)


def _to_logs_view(view: LogsView) -> contracts.LogsView:
    return contracts.LogsView(
        id=view.id,
        short_id=view.short_id,
        name=view.name,
        filters=view.filters or {},
        pinned=view.pinned,
        created_at=view.created_at,
        updated_at=view.updated_at,
        created_by=_to_user_basic_info(view.created_by),
    )


def _get_logs_view(team_id: int, short_id: str) -> LogsView:
    try:
        return LogsView.objects.select_related("created_by").get(team_id=team_id, short_id=short_id)
    except LogsView.DoesNotExist:
        raise LogsViewNotFoundError(short_id)


def logs_views_queryset(team_id: int) -> QuerySet[LogsView]:
    """A team's saved views, newest first — returned lazily so the caller paginates at
    the DB (DRF applies LIMIT/OFFSET in SQL). Map the page to contracts with map_logs_views."""
    return LogsView.objects.filter(team_id=team_id).select_related("created_by").order_by("-created_at")


def map_logs_views(views: Iterable[LogsView]) -> list[contracts.LogsView]:
    return [_to_logs_view(v) for v in views]


def get_logs_view(team_id: int, short_id: str) -> contracts.LogsView:
    return _to_logs_view(_get_logs_view(team_id, short_id))


def create_logs_view(
    team_id: int, created_by: "User | None", name: str, filters: dict, pinned: bool
) -> contracts.LogsView:
    # Pass the user object (not just its id) so Django caches it on the instance —
    # _to_logs_view then reads created_by without a second SELECT.
    view = LogsView.objects.create(team_id=team_id, created_by=created_by, name=name, filters=filters, pinned=pinned)
    return _to_logs_view(view)


def update_logs_view(team_id: int, short_id: str, **fields: object) -> contracts.LogsView:
    view = _get_logs_view(team_id, short_id)
    if fields:
        for key, value in fields.items():
            setattr(view, key, value)
        view.save(update_fields=[*fields.keys(), "updated_at"])
    return _to_logs_view(view)


def delete_logs_view(team_id: int, short_id: str) -> contracts.LogsView:
    view = _get_logs_view(team_id, short_id)
    deleted = _to_logs_view(view)
    view.delete()
    return deleted
