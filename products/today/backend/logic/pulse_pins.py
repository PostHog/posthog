from pydantic import TypeAdapter, ValidationError

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
    kept: list[contracts.PulsePin] = []
    for pin in pins:
        if all(existing.key != pin.key for existing in kept):
            kept.append(pin)
    kept = kept[:MAX_PULSE_PINS]
    TodayPulsePins.objects.for_team(team_id).update_or_create(
        team_id=team_id, user_id=user_id, defaults={"pins": _PINS.dump_python(kept, mode="json")}
    )
    return kept


def delete_for_teams(team_ids: list[int]) -> None:
    TodayPulsePins.objects.unscoped().filter(team_id__in=team_ids).delete()
