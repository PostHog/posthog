from django.db import IntegrityError, transaction
from django.utils import timezone

from pydantic import TypeAdapter, ValidationError

from posthog.models.scoping.manager import resolve_effective_team_id

from ..facade import contracts
from ..models import TodayPulsePins

MAX_PULSE_PINS = 4

_PINS = TypeAdapter(list[contracts.PulsePin])


def get_pins(*, team_id: int, user_id: int) -> list[contracts.PulsePin]:
    row = TodayPulsePins.objects.for_team(team_id).filter(user_id=user_id).first()
    if row is None:
        return []
    try:
        return _PINS.validate_python(row.pins)
    except ValidationError:
        return []


def set_pins(*, team_id: int, user_id: int, pins: list[contracts.PulsePin]) -> list[contracts.PulsePin]:
    team_id = resolve_effective_team_id(team_id)
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


def delete_for_teams(team_ids: list[int]) -> None:
    TodayPulsePins.objects.unscoped().filter(team_id__in=team_ids).delete()
