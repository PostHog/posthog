"""Numbers a space watches. Each row is a reference to a saved insight, never a value."""

from uuid import UUID

from django.db.models import Max, QuerySet

from products.docs.backend.logic.documents import ChannelNotVisibleError
from products.docs.backend.models import SpaceKpi
from products.tasks.backend.facade.api import channel_exists, visible_channels_q


def visible_kpis(team_id: int, user_id: int | None) -> QuerySet[SpaceKpi]:
    return (
        SpaceKpi.objects.unscoped()
        .filter(visible_channels_q(user_id, relation="channel"), team_id=team_id, deleted=False)
        .select_related("created_by")
    )


def kpis_in_channel(team_id: int, user_id: int | None, channel_id: str | UUID) -> QuerySet[SpaceKpi]:
    return visible_kpis(team_id, user_id).filter(channel_id=channel_id).order_by("position", "created_at")


def soft_delete_kpi(kpi: SpaceKpi) -> None:
    kpi.deleted = True
    kpi.save(update_fields=["deleted"])


def create_kpi(*, team_id: int, user_id: int, channel_id: str | UUID, name: str, insight_short_id: str) -> SpaceKpi:
    if not channel_exists(team_id, channel_id, user_id):
        raise ChannelNotVisibleError("Channel not found in this team.")

    last = (
        SpaceKpi.objects.unscoped()
        .filter(team_id=team_id, channel_id=channel_id, deleted=False)
        .aggregate(top=Max("position"))["top"]
    )
    return SpaceKpi.objects.create(
        team_id=team_id,
        channel_id=channel_id,
        created_by_id=user_id,
        name=name,
        insight_short_id=insight_short_id,
        position=0 if last is None else last + 1,
    )
