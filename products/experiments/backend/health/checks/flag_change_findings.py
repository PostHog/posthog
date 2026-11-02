"""
What the findings about flag changes after launch share besides their words, and the finding for a flag history that
the reader can't view. Pure functions, no I/O: `health/exposure_gate.py` loads the changes and the exposure answers.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
)
from products.experiments.backend.health.checks.change_wording import (
    delay,
    duration,
    not_checked_because,
    not_checked_next_step,
    suggested_start,
    the_change,
)
from products.experiments.backend.health.context import (
    MIN_EXPOSED_UNITS_TO_WARN,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    HealthContext,
)
from products.experiments.backend.health.skips import (
    NEEDS_VARIANTS,
    CheckOutcome,
    CheckSkip,
    flag_to_check,
    not_applicable,
    not_checked,
)

# pinned: the subcode of a flag history that was not checked against the exposures. The page sends it as
# `finding_subcode` on the health finding events.
NOT_CHECKED = "not_checked"

EvidenceValue = str | int | float | bool | None

# The reasons for which the flag history is not read, so no change is known.
_HISTORY_NOT_READ = frozenset(
    {
        FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS,
        FlagHistoryNotCheckedReason.TOO_MANY_SAVES,
        FlagHistoryNotCheckedReason.TOO_MANY_CONDITIONS,
    }
)


class _Change(Protocol):
    @property
    def changed_at(self) -> datetime: ...


class ChangeEffect(Protocol):
    """The net effect of the changes of one kind, as each kind's module computes it."""

    @property
    def first(self) -> _Change: ...

    @property
    def last(self) -> _Change: ...

    @property
    def change_count(self) -> int: ...


def history_to_check(ctx: HealthContext) -> FlagHistory | FlagHistoryNotChecked | CheckSkip:
    """The flag history that the flag-history checks read, or why they don't look, in the order the reader is most
    likely to act on."""
    flag = flag_to_check(ctx, before_launch=False)
    if isinstance(flag, CheckSkip):
        return flag
    # `flag_variants_mismatch` reports a flag without variants, and the variants have to come back first.
    if not any(variant.key for variant in flag.variants):
        return not_applicable(NEEDS_VARIANTS)
    # The health endpoint loads the history for every state that reaches here, and so does the exposure answer before
    # `srm` reads it, so None means that the load failed.
    if ctx.flag_history is None:
        return not_checked("Couldn't check because the flag history failed to load")
    return ctx.flag_history


def changes_to_check(ctx: HealthContext) -> FlagHistory | FlagHistoryNotChecked | CheckSkip:
    """The flag history that the checks of one kind of change read, or why they don't look."""
    history = history_to_check(ctx)
    # Without the history no change is known. `flag_history_not_readable` reports why.
    if isinstance(history, FlagHistoryNotChecked) and history.reason in _HISTORY_NOT_READ:
        return not_checked(f"Couldn't check because {not_checked_because(history.reason)}")
    return history


def flag_history_not_readable(ctx: HealthContext) -> CheckOutcome:
    """One finding for every kind of change when the flag's history is not read."""
    history = history_to_check(ctx)
    if isinstance(history, CheckSkip):
        return history
    if not isinstance(history, FlagHistoryNotChecked) or history.reason not in _HISTORY_NOT_READ:
        return None
    no_access = history.reason == FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS
    return ExperimentHealthFinding(
        # pinned: insights and the page read this code and subcode for this finding.
        code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
        subcode=NOT_CHECKED,
        severity=ExperimentHealthFindingSeverity.INFO,
        title="The flag history was not checked",
        detail=(
            "This check can't see whether the flag's variant split, key, bucketing or release conditions "
            f"changed after launch, because {not_checked_because(history.reason)}. "
            + (
                "Viewing the history needs viewer access to the flag and, with an API key, the activity_log:read scope."
                if no_access
                else "Review the flag history."
            )
        ),
        reason=history.reason.value,
        evidence={},
        # The flag history is the page this caller can't open.
        actions=() if no_access else (ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref="E3",
    )


def change_finding(
    history: FlagHistory,
    effect: ChangeEffect,
    *,
    kind: ExperimentHealthFlagChangeKind,
    code: ExperimentHealthFindingCode,
    subcode: str,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    sentences: Sequence[str],
    kind_evidence: Mapping[str, EvidenceValue],
    diagnostic_ref: str,
    reason: str | None = None,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=code,
        subcode=subcode,
        reason=reason,
        severity=severity,
        title=title,
        detail=" ".join(sentences),
        evidence={
            **change_evidence(
                history, effect, kind_evidence=kind_evidence, exposed_before_change=history.exposed_before_first
            ),
            # pinned: capped at MIN_EXPOSED_UNITS_TO_WARN, so the cap means "at least". None when unknown.
            "units_exposed_before_last_change": history.exposed_units_before_last.get(kind),
        },
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref=diagnostic_ref,
    )


def few_exposed_units(history: FlagHistory, kind: ExperimentHealthFlagChangeKind) -> int | None:
    """The persons or groups exposed before the last counted change of a kind, when they are too few for a warning.
    None when there were enough, or when the count is unknown, which keeps the warning."""
    count = history.exposed_units_before_last.get(kind)
    return count if count is not None and count < MIN_EXPOSED_UNITS_TO_WARN else None


def exposed_when(history: FlagHistory, effect: ChangeEffect, count: int) -> str:
    after_launch = duration((effect.last.changed_at - history.launched_at).total_seconds())
    change = "The change" if effect.change_count == 1 else "The last change"
    return f"{change} came {after_launch} after launch, when {_units(count, history.counts_groups)} had been exposed."


def leave_out(history: FlagHistory, effect: ChangeEffect, count: int) -> list[str]:
    """The next step for the few persons or groups exposed before the last change. Empty when there were none."""
    if count == 0:
        return []
    start_at = suggested_start(effect.last.changed_at, history.team_timezone)
    return [f"Move the start date to {start_at} so the results count only exposures after it."]


def _units(count: int, counts_groups: bool) -> str:
    if count == 0:
        return "no group" if counts_groups else "nobody"
    if counts_groups:
        return "1 group" if count == 1 else f"{count} groups"
    return "1 person" if count == 1 else f"{count} people"


def not_checked_finding(
    history: FlagHistoryNotChecked,
    effect: ChangeEffect,
    *,
    code: ExperimentHealthFindingCode,
    title: str,
    what_changed: Sequence[str],
    kind_evidence: Mapping[str, EvidenceValue],
    diagnostic_ref: str,
) -> ExperimentHealthFinding:
    change = the_change(effect.change_count, "the")
    return ExperimentHealthFinding(
        code=code,
        subcode=NOT_CHECKED,
        reason=history.reason.value,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=title,
        detail=" ".join(
            [
                *what_changed,
                f"This check can't tell whether anyone was exposed before {change}, because "
                f"{not_checked_because(history.reason)}.",
                not_checked_next_step(history.reason, change),
            ]
        ),
        evidence=change_evidence(history, effect, kind_evidence=kind_evidence, exposed_before_change=None),
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref=diagnostic_ref,
    )


def change_evidence(
    history: FlagHistory | FlagHistoryNotChecked,
    effect: ChangeEffect,
    *,
    kind_evidence: Mapping[str, EvidenceValue],
    exposed_before_change: bool | None,
) -> dict[str, EvidenceValue]:
    return {
        "change_count": effect.change_count,
        "first_changed_at": effect.first.changed_at.astimezone(UTC).isoformat(),
        "last_changed_at": effect.last.changed_at.astimezone(UTC).isoformat(),
        **kind_evidence,
        "exposed_before_change": exposed_before_change,
        "seconds_after_launch": int((effect.first.changed_at - history.launched_at).total_seconds()),
    }


def delay_after_launch(history: FlagHistory, effect: ChangeEffect) -> list[str]:
    return delay(
        launched_at=history.launched_at,
        first_changed_at=effect.first.changed_at,
        exposed_before_first=history.exposed_before_first,
        change_count=effect.change_count,
    )
