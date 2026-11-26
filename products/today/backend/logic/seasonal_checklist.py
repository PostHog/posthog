"""The seasonal checklist: the active campaign, and the handler behind each item's action."""

from abc import ABC, abstractmethod
from datetime import datetime

from django.db.models import F, Q

import structlog
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from posthog.models import Team, User

from ..facade.contracts import SeasonalAction, SeasonalChecklist, SeasonalChecklistItem
from ..facade.enums import HogAccessory, SeasonalActionKind, SeasonalItemIcon
from ..models import SeasonalCampaign, SeasonalCampaignItem

logger = structlog.get_logger(__name__)


class ActionHandler(ABC):
    settings_model: type[BaseModel]

    @abstractmethod
    def action(self, settings: BaseModel) -> SeasonalAction: ...

    def is_done(self, team: Team, user: User, settings: BaseModel) -> bool | None:
        return None


class _AskAiSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=2000)


class _AskAiHandler(ActionHandler):
    settings_model = _AskAiSettings

    def action(self, settings: BaseModel) -> SeasonalAction:
        assert isinstance(settings, _AskAiSettings)
        return SeasonalAction(kind=SeasonalActionKind.ASK_AI, prompt=settings.prompt)


HANDLERS: dict[SeasonalActionKind, ActionHandler] = {
    SeasonalActionKind.ASK_AI: _AskAiHandler(),
}


class InvalidActionSettings(ValueError):
    pass


def parse_action_settings(kind: str, settings: object) -> BaseModel:
    handler = HANDLERS.get(SeasonalActionKind(kind)) if kind in SeasonalActionKind.values else None
    if handler is None:
        raise InvalidActionSettings(f"No handler for the action {kind!r}.")
    try:
        return handler.settings_model.model_validate(settings)
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'settings'}: {e['msg']}" for e in error.errors())
        raise InvalidActionSettings(problems) from error


def active_campaign(now: datetime) -> SeasonalCampaign | None:
    return (
        SeasonalCampaign.objects.filter(is_active=True)
        .filter(Q(starts_at__isnull=True) | Q(starts_at__lte=now))
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .order_by(F("starts_at").desc(nulls_last=True), "-created_at")
        .prefetch_related("items")
        .first()
    )


def _item(team: Team, user: User, item: SeasonalCampaignItem) -> SeasonalChecklistItem | None:
    try:
        settings = parse_action_settings(item.action_kind, item.action_settings)
    except InvalidActionSettings:
        logger.warning("today_seasonal_item_skipped", item_id=str(item.id), action_kind=item.action_kind)
        return None
    handler = HANDLERS[SeasonalActionKind(item.action_kind)]
    return SeasonalChecklistItem(
        key=item.key,
        title=item.title,
        description=item.description,
        icon=SeasonalItemIcon(item.icon) if item.icon else None,
        action=handler.action(settings),
        done=handler.is_done(team, user, settings),
    )


def seasonal_checklist(team: Team, user: User, now: datetime) -> SeasonalChecklist | None:
    campaign = active_campaign(now)
    if campaign is None:
        return None
    items = [found for item in campaign.items.all() if (found := _item(team, user, item)) is not None]
    if not items:
        return None
    return SeasonalChecklist(
        campaign=campaign.key,
        title=campaign.title,
        description=campaign.description,
        reason=campaign.reason or None,
        badge=campaign.badge or None,
        bubble=campaign.bubble,
        done_title=campaign.done_title,
        done_description=campaign.done_description,
        accessories=[HogAccessory(accessory) for accessory in campaign.accessories],
        snow=campaign.snow,
        lights=campaign.lights,
        items=items,
    )
