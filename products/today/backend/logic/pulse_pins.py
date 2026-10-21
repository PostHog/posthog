from django.db import IntegrityError, transaction
from django.utils import timezone

from pydantic import TypeAdapter, ValidationError

from posthog.models import Team
from posthog.scopes import scopes_not_covered

from ..facade import contracts
from ..models import TodayPulsePins

MAX_PULSE_PINS = 4
INSIGHT_PREFIX = "insight:"

_PINS = TypeAdapter(list[contracts.PulsePin])


def required_scopes(key: str, dashboard_id: int | None) -> tuple[str, ...]:
    if not key.startswith(INSIGHT_PREFIX):
        return ("customer_analytics:read",)
    return ("insight:read",) if dashboard_id is None else ("insight:read", "dashboard:read")


def get_pins(*, team: Team, user_id: int, scopes: frozenset[str] | None) -> list[contracts.PulsePin]:
    row = TodayPulsePins.objects.for_team(_canonical(team), canonical=True).filter(user_id=user_id).first()
    if row is None:
        return []
    try:
        pins = _PINS.validate_python(row.pins)
    except ValidationError:
        return []
    if scopes is None or "*" in scopes:
        return pins
    return [pin for pin in pins if not scopes_not_covered(scopes, required_scopes(pin.key, pin.dashboard_id))]


def set_pins(*, team: Team, user_id: int, pins: list[contracts.PulsePin]) -> list[contracts.PulsePin]:
    team_id = _canonical(team)
    kept: dict[str, contracts.PulsePin] = {}
    for pin in pins:
        kept.setdefault(pin.key, pin)
        if len(kept) == MAX_PULSE_PINS:
            break
    kept_pins = list(kept.values())
    stored = _PINS.dump_python(kept_pins, mode="json")
    try:
        with transaction.atomic():
            TodayPulsePins.objects.for_team(team_id, canonical=True).update_or_create(
                team_id=team_id, user_id=user_id, defaults={"pins": stored}
            )
    except IntegrityError:
        TodayPulsePins.objects.for_team(team_id, canonical=True).filter(user_id=user_id).update(
            pins=stored, updated_at=timezone.now()
        )
    return kept_pins


def _canonical(team: Team) -> int:
    return team.parent_team_id or team.id


def delete_for_teams(team_ids: list[int]) -> None:
    TodayPulsePins.objects.unscoped().filter(team_id__in=team_ids).delete()
