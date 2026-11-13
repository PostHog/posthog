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
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.bucketing_changes import GroupTypeNames, describe_bucketing_value
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
    FlagChange,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    HealthContext,
)
from products.experiments.backend.health.skips import (
    NEEDS_VARIANTS,
    CheckOutcome,
    CheckRows,
    CheckSkip,
    flag_to_check,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.split_changes import split_value
from products.feature_flags.backend.facade.edits import (
    BucketingChange,
    BucketingSetting,
    ConditionsChange,
    ReleaseCondition,
    SplitChange,
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


def change_rows(ctx: HealthContext, kind: type[FlagChange]) -> CheckRows:
    """The changes of one kind since the start date, each with whether anyone was exposed before it."""
    history = changes_to_check(ctx)
    if isinstance(history, CheckSkip):
        return ()
    return tuple(
        {
            ExperimentHealthValueKey.CHANGED_AT: change.changed_at.astimezone(UTC).isoformat(),
            **_described(change, history.group_type_names),
            ExperimentHealthValueKey.BEFORE_EXPOSURE: _before_exposure(history, change.changed_at),
        }
        for change in history.of_kind(kind)
    )


# The settings as the flag page labels them.
_SETTING_LABELS = {
    BucketingSetting.KEY: "Flag key",
    BucketingSetting.AGGREGATION: "Match by",
    BucketingSetting.BUCKETING_IDENTIFIER: "Match by",
    BucketingSetting.EXPERIENCE_CONTINUITY: "Persist flag across authentication steps",
}


def _described(change: FlagChange, group_type_names: GroupTypeNames) -> dict[ExperimentHealthValueKey, str]:
    match change:
        case SplitChange():
            return {
                ExperimentHealthValueKey.BEFORE: split_value(change.before),
                ExperimentHealthValueKey.AFTER: split_value(change.after),
            }
        case BucketingChange():
            return {
                ExperimentHealthValueKey.CHANGED_SETTING: _SETTING_LABELS[change.setting],
                ExperimentHealthValueKey.BEFORE: _sentence_case(
                    describe_bucketing_value(change.setting, change.before, group_type_names=group_type_names)
                ),
                ExperimentHealthValueKey.AFTER: _sentence_case(
                    describe_bucketing_value(change.setting, change.after, group_type_names=group_type_names)
                ),
            }
        case ConditionsChange():
            return {
                ExperimentHealthValueKey.BEFORE: _describe_conditions(change.before),
                ExperimentHealthValueKey.AFTER: _describe_conditions(change.after),
            }


def _describe_conditions(conditions: tuple[ReleaseCondition, ...]) -> str:
    """The release conditions in the flag page's order, one set per line, for example 'Set 1: 100%, filters on plan'."""
    if not conditions:
        return "None"
    sets = []
    for number, condition in enumerate(conditions, start=1):
        parts = [f"Set {number}: {condition.rollout:g}%"]
        if condition.property_keys:
            parts.append(f"filters on {', '.join(sorted({_filter_name(key) for key in condition.property_keys}))}")
        if condition.variant:
            parts.append(f'forces "{condition.variant}"')
        sets.append(", ".join(parts))
    return "\n".join(sets)


def _sentence_case(text: str) -> str:
    # The findings use these words mid-sentence, so they start lowercase. A quoted flag key keeps its case.
    return text[:1].upper() + text[1:]


def _filter_name(property_key: str) -> str:
    # The facade keys a filter as "<type>:<key>", and a cohort filter's key is the cohort id.
    kind, _, key = property_key.partition(":")
    return "cohort" if kind == "cohort" else key


def _before_exposure(history: FlagHistory | FlagHistoryNotChecked, changed_at: datetime) -> bool | None:
    """Whether nobody was exposed before the change. None when unknown."""
    # A history that wasn't compared with the exposures can't tell.
    if isinstance(history, FlagHistoryNotChecked):
        return None
    if history.counted_since is None or changed_at < history.counted_since:
        return True
    # The counting starts at the first change with an exposure before it, or with an unknown answer. After an unknown
    # answer, nobody may have been exposed before any of the changes that follow.
    return None if history.exposed_before_first is None else False


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
    suggested_start_date: datetime | None = None,
    end_experiment: bool = False,
) -> ExperimentHealthFinding:
    """`suggested_start_date` is the start date that the sentences name, from `suggested_start_at`. The page's button
    moves the start date to this value, so the two must agree."""
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
            # pinned: the start date that MOVE_START_DATE sets, in UTC.
            **(
                {"suggested_start_date": suggested_start_date.astimezone(UTC).isoformat()}
                if suggested_start_date is not None
                else {}
            ),
        },
        actions=(
            *((ExperimentHealthFindingActionKind.MOVE_START_DATE,) if suggested_start_date is not None else ()),
            *((ExperimentHealthFindingActionKind.END_EXPERIMENT,) if end_experiment else ()),
            ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,
        ),
        diagnostic_ref=diagnostic_ref,
    )


def few_exposed_units(history: FlagHistory, kind: ExperimentHealthFlagChangeKind) -> int | None:
    """The persons or groups exposed before the last counted change of a kind, when they are too few for a warning.
    None when there were enough, or when the count is unknown, which keeps the warning."""
    count = history.exposed_units_before_last.get(kind)
    return count if count is not None and count < MIN_EXPOSED_UNITS_TO_WARN else None


def exposed_when(history: FlagHistory, effect: ChangeEffect, count: int) -> str:
    after_start = duration((effect.last.changed_at - history.start_date).total_seconds())
    change = "The change" if effect.change_count == 1 else "The last change"
    return f"{change} came {after_start} after the start date, when {_units(count, history.counts_groups)} had been exposed."


def count_only_after(changed_at: datetime, team_timezone: str) -> str:
    start_at = suggested_start(changed_at, team_timezone)
    return f"Move the start date to {start_at} so the results count only exposures after it."


def leave_out(history: FlagHistory, effect: ChangeEffect, count: int) -> list[str]:
    """The next step for the few persons or groups exposed before the last change. Empty when there were none."""
    if count == 0:
        return []
    return [count_only_after(effect.last.changed_at, history.team_timezone)]


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
        "seconds_after_start": int((effect.first.changed_at - history.start_date).total_seconds()),
    }


def delay_after_launch(history: FlagHistory, effect: ChangeEffect) -> list[str]:
    return delay(
        start_date=history.start_date,
        first_changed_at=effect.first.changed_at,
        exposed_before_first=history.exposed_before_first,
        change_count=effect.change_count,
    )
