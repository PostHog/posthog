import json
from typing import Any

from posthog.dataclasses import frozen

from products.wizard.backend.facade.contracts import WizardSpendRange
from products.wizard.backend.facade.enums import WizardSpendEffort, WizardSpendFixLocation
from products.wizard.backend.logic.results.config import (
    MAX_RESULT_IDS,
    MAX_RESULT_SAVINGS,
    MAX_RESULT_TEXT_LENGTH,
    WIZARD_RESULT_VERSION,
)

_RESULT_FIELDS = frozenset(
    {"version", "notebook_short_id", "dashboard_ids", "insight_ids", "savings", "value_items", "checks_passed"}
)
_SAVING_FIELDS = frozenset(
    {"id", "title", "billing_type", "unit", "before", "after", "evidence", "tradeoff", "effort", "fixed_in"}
)


class InvalidProgramResultError(ValueError):
    pass


@frozen
class SavingClaim:
    """One change the agent sized: the billable volume a month before it and the range expected after."""

    id: str
    title: str
    billing_type: str
    unit: str
    volume_before: float
    volume_after: WizardSpendRange
    evidence: str
    tradeoff: str
    effort: WizardSpendEffort
    fixed_in: WizardSpendFixLocation

    @property
    def volume_removed(self) -> WizardSpendRange:
        # The smallest removal comes from the highest expected volume after the change.
        return WizardSpendRange(
            low=self.volume_before - self.volume_after.high,
            high=self.volume_before - self.volume_after.low,
        )


@frozen
class ProgramResult:
    notebook_short_id: str
    dashboard_ids: tuple[int, ...]
    insight_ids: tuple[int, ...]
    savings: tuple[SavingClaim, ...]


def parse_program_result(raw: bytes) -> ProgramResult:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise InvalidProgramResultError("The result file is not valid JSON") from error

    if not isinstance(decoded, dict) or not set(decoded).issubset(_RESULT_FIELDS):
        raise InvalidProgramResultError("The result file has unknown fields")
    if decoded.get("version") != WIZARD_RESULT_VERSION:
        raise InvalidProgramResultError("The result file has an unsupported version")

    savings = decoded.get("savings", [])
    if not isinstance(savings, list) or len(savings) > MAX_RESULT_SAVINGS:
        raise InvalidProgramResultError("Invalid savings list")

    claims = tuple(_parse_saving(saving) for saving in savings)
    if len({claim.id for claim in claims}) != len(claims):
        raise InvalidProgramResultError("Saving ids must be unique")

    return ProgramResult(
        notebook_short_id=_text(decoded.get("notebook_short_id"), max_length=64),
        dashboard_ids=_ids(decoded.get("dashboard_ids", [])),
        insight_ids=_ids(decoded.get("insight_ids", [])),
        savings=claims,
    )


def _parse_saving(value: Any) -> SavingClaim:
    if not isinstance(value, dict) or set(value) != _SAVING_FIELDS:
        raise InvalidProgramResultError("Invalid saving")

    after = value["after"]
    if not isinstance(after, dict) or set(after) != {"low", "high"}:
        raise InvalidProgramResultError("Invalid saving range")

    before = _number(value["before"])
    try:
        volume_after = WizardSpendRange(low=_number(after["low"]), high=_number(after["high"]))
        effort = WizardSpendEffort(value["effort"])
        fixed_in = WizardSpendFixLocation(value["fixed_in"])
    except ValueError as error:
        raise InvalidProgramResultError("Invalid saving") from error

    if volume_after.high > before:
        raise InvalidProgramResultError("A saving cannot raise volume")

    return SavingClaim(
        id=_text(value["id"], max_length=64),
        title=_text(value["title"]),
        billing_type=_text(value["billing_type"], max_length=64),
        unit=_text(value["unit"], max_length=64),
        volume_before=before,
        volume_after=volume_after,
        evidence=_text(value["evidence"]),
        tradeoff=_text(value["tradeoff"]),
        effort=effort,
        fixed_in=fixed_in,
    )


def _text(value: Any, *, max_length: int = MAX_RESULT_TEXT_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise InvalidProgramResultError("Invalid text field")
    return value.strip()


def _number(value: Any) -> float:
    # bool is an int subclass, and a JSON true must not pass as a volume.
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise InvalidProgramResultError("Invalid number")
    return float(value)


def _ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) > MAX_RESULT_IDS:
        raise InvalidProgramResultError("Invalid id list")
    if not all(isinstance(item, int) and not isinstance(item, bool) and item > 0 for item in value):
        raise InvalidProgramResultError("Invalid id list")
    return tuple(dict.fromkeys(value))
