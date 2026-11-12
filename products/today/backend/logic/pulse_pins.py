from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from pydantic import TypeAdapter, ValidationError

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.scopes import scopes_not_covered

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade.api import get_key_metric_names
from products.product_analytics.backend.facade.api import viewable_insight_definitions

from ..facade import contracts
from ..models import TodayPulsePins
from .highlight_registry import load_sources
from .highlight_types import allows

MAX_PULSE_PINS = 4
MAX_HIDDEN_NUMBERS = 50
INSIGHT_PREFIX = "insight:"
UNTITLED_INSIGHT = "Untitled insight"

_PINS = TypeAdapter(list[contracts.PulsePin])


@frozen
class PulseChoices:
    pins: list[contracts.PulsePin]
    hidden: list[str]


def required_scopes(key: str, dashboard_id: int | None) -> tuple[str, ...]:
    if not key.startswith(INSIGHT_PREFIX):
        return ("customer_analytics:read",)
    return ("insight:read",) if dashboard_id is None else ("insight:read", "dashboard:read")


def get_choices(*, team: Team, user_id: int, scopes: frozenset[str] | None) -> PulseChoices:
    row = (
        TodayPulsePins.objects.for_team(_canonical(team), canonical=True)
        .filter(user_id=user_id)
        .values("pins", "hidden")
        .first()
    )
    if row is None:
        return PulseChoices(pins=[], hidden=[])
    try:
        pins = _PINS.validate_python(row["pins"])
    except ValidationError:
        pins = []
    return PulseChoices(
        pins=[pin for pin in pins if _covered(scopes, pin.key, pin.dashboard_id)],
        hidden=[key for key in row["hidden"] or [] if isinstance(key, str)],
    )


def set_pins(*, team: Team, user_id: int, pins: list[contracts.PulsePin]) -> list[contracts.PulsePin]:
    kept: dict[str, contracts.PulsePin] = {}
    for pin in pins:
        kept.setdefault(pin.key, pin)
        if len(kept) == MAX_PULSE_PINS:
            break
    kept_pins = list(kept.values())
    _save(team, user_id, pins=_PINS.dump_python(kept_pins, mode="json"))
    return kept_pins


def set_hidden(*, team: Team, user_id: int, keys: list[str]) -> list[str]:
    kept = list(dict.fromkeys(keys))[-MAX_HIDDEN_NUMBERS:]
    _save(team, user_id, hidden=kept)
    return kept


def named_hidden(
    *, team: Team, user: User, keys: list[str], scopes: frozenset[str] | None
) -> list[contracts.HiddenPulseNumber]:
    access = UserAccessControl(user=user, team=team)
    others = [key for key in keys if not key.startswith(INSIGHT_PREFIX)]
    product_names = _product_number_names(team, user, access, scopes, others) if others else {}
    visible = [key for key in keys if key in product_names or allows(access, scopes, *required_scopes(key, None))]
    short_ids = [key.removeprefix(INSIGHT_PREFIX) for key in visible if key.startswith(INSIGHT_PREFIX)]
    insights = viewable_insight_definitions(team=team, user=user, short_ids=short_ids) if short_ids else {}
    key_metrics = get_key_metric_names(team=team) if len(short_ids) + len(product_names) < len(visible) else {}
    names = {
        **{f"{INSIGHT_PREFIX}{short_id}": insight.name or UNTITLED_INSIGHT for short_id, insight in insights.items()},
        **key_metrics,
        **product_names,
    }
    return [contracts.HiddenPulseNumber(key=key, name=names[key]) for key in visible if key in names]


def _product_number_names(
    team: Team, user: User, access: UserAccessControl, scopes: frozenset[str] | None, keys: list[str]
) -> dict[str, str]:
    names: dict[str, str] = {}
    for source in load_sources():
        if source.number_names is None or not allows(access, scopes, *source.scopes):
            continue
        try:
            named = source.number_names(team, user, keys)
        except Exception as error:
            capture_exception(error, {"source": source.name, "team_id": team.id, "product": "today"})
            continue
        names.update({key: name for key, name in named.items() if key in keys})
    return names


def delete_for_teams(team_ids: list[int]) -> None:
    TodayPulsePins.objects.unscoped().filter(team_id__in=team_ids).delete()


def _covered(scopes: frozenset[str] | None, key: str, dashboard_id: int | None) -> bool:
    return scopes is None or "*" in scopes or not scopes_not_covered(scopes, required_scopes(key, dashboard_id))


def _save(team: Team, user_id: int, **fields: Any) -> None:
    team_id = _canonical(team)
    try:
        with transaction.atomic():
            TodayPulsePins.objects.for_team(team_id, canonical=True).update_or_create(
                team_id=team_id, user_id=user_id, defaults=fields
            )
    except IntegrityError:
        TodayPulsePins.objects.for_team(team_id, canonical=True).filter(user_id=user_id).update(
            **fields, updated_at=timezone.now()
        )


def _canonical(team: Team) -> int:
    return team.parent_team_id or team.id
