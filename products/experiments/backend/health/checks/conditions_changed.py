"""
The release conditions of the experiment's flag changed after launch while people were already exposed. Pure
functions, no I/O: `health/exposure_gate.py` loads the changes and the exposure answers.

A condition added, removed or with other criteria moves people into or out of the experiment. The people exposed
before stay in the results, so the results mix two audiences. That is information, so it is graded info. A new
order of conditions that serve different variants moves the people who match several of them to another variant.
How many is unknown, so that is info too.

A variant override that was removed moves the people its condition matches from its variant to a random one, and
their exposures under that variant stay in the results. It is graded by the share of that variant's users the
condition serves, as the forced-variant check grades an override in place. When fewer than MIN_EXPOSED_UNITS_TO_WARN
were exposed before the last change, a warning by that grade is info, because so few can't move the results. An
override that is still in place is the forced-variant check's to report, so it is not reported here.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
)
from products.experiments.backend.health.checks.change_wording import suggested_start, the_change
from products.experiments.backend.health.checks.flag_change_findings import (
    change_finding,
    changes_not_checked,
    exposed_when,
    few_exposed_units,
    history_to_check,
    leave_out,
    not_checked_finding,
)
from products.experiments.backend.health.condition_changes import (
    ConditionsChangeShape,
    ConditionsNetEffect,
    RemovedOverride,
    conditions_net_effect,
)
from products.experiments.backend.health.context import (
    ConditionsChange,
    FlagHistory,
    FlagHistoryNotChecked,
    HealthContext,
    ReachableCondition,
)
from products.experiments.backend.health.pinned_share import (
    PinnedConditions,
    PinnedShareGrade,
    PinnedShareUnknownReason,
    grade_pinned_share,
    percent,
    pinned_conditions,
    pinned_share_severity,
)
from products.experiments.backend.health.split_changes import format_change_time

_TITLE = "The release conditions changed after launch"
_OVERRIDE_TITLE = "A variant override was removed after launch"
_REORDERED_TITLE = "The order of the release conditions changed after launch"
_REVERTED_TITLE = "The release conditions changed and were set back"
_NOT_CHECKED_TITLE = "Release condition changes were not checked"


def release_conditions_changed_mid_run(ctx: HealthContext) -> ExperimentHealthFinding | None:
    history = history_to_check(ctx)
    if history is None:
        return None
    if isinstance(history, FlagHistoryNotChecked):
        return _not_checked(history)
    effect = conditions_net_effect(history.counted(ConditionsChange), current=history.release_conditions)
    if effect is None:
        return None
    # Conditions set back with nobody exposed in between left no trace in the results.
    if (
        effect.shape == ConditionsChangeShape.REVERTED
        and history.exposed_between.get(ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS) is False
    ):
        return None
    removed = _reported(ctx, history, effect)
    if removed:
        finding = _override_removed(ctx, history, effect, removed)
        if finding is not None:
            return finding
    change = the_change(effect.change_count, "the")
    if effect.reordered:
        return _finding(
            history,
            effect,
            subcode=ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED,
            title=_REORDERED_TITLE,
            sentences=[
                f"{_changed(history, effect)}{_condition_counts(effect)}, and conditions that serve different "
                "variants now come in another order.",
                "Users who match more than one of them now get the variant of another condition, so those exposed "
                f"before {change} may have switched variants. Their exposures stay in the results.",
                f"Review {change} in the flag history.",
            ],
            diagnostic_ref="A7",
        )
    if effect.audience_changed:
        return _finding(
            history,
            effect,
            subcode=ConditionsChangeShape.CONDITIONS_CHANGED,
            title=_TITLE,
            sentences=[
                f"{_changed(history, effect)}{_condition_counts(effect)}.",
                f"People who match differently now enter or leave the experiment, and people exposed before {change} "
                "stay in the results.",
                *_edited_overrides(effect),
                f"Review {change} in the flag history.",
            ],
        )
    # Only an override changed. The forced-variant check reports one that is still in place, and the removed ones
    # were graded above.
    if effect.shape != ConditionsChangeShape.REVERTED or removed:
        return None
    return _finding(
        history,
        effect,
        subcode=ConditionsChangeShape.REVERTED,
        title=_REVERTED_TITLE,
        sentences=[
            _set_back(history, effect),
            "People exposed in between were targeted by other conditions, and they stay in the results.",
            f"Review {change} in the flag history.",
        ],
    )


def _edited_overrides(effect: ConditionsNetEffect) -> list[str]:
    edited = effect.edited_overrides
    if not edited:
        return []
    if len(edited) == 1:
        return [
            f'Set {edited[0].condition_number} has the variant override "{edited[0].variant}", so users who now match '
            "it or no longer match it may also have switched variants."
        ]
    numbers = [override.condition_number for override in edited]
    names = ", ".join(str(number) for number in numbers[:-1]) + f" and {numbers[-1]}"
    return [
        f"Sets {names} have variant overrides, so users who now match them or no longer match them may also have "
        "switched variants."
    ]


def removed_overrides_to_grade(ctx: HealthContext) -> PinnedConditions | None:
    """The overrides removed after launch, as pins on the conditions that held them, which the finding is graded
    by as if they were still in place. None when no removed override has a condition left to count its users."""
    history = ctx.flag_history
    flag = ctx.flag
    if not isinstance(history, FlagHistory) or flag is None or flag.deleted or not ctx.is_running or ctx.archived:
        return None
    effect = conditions_net_effect(history.counted(ConditionsChange), current=history.release_conditions)
    if effect is None:
        return None
    removed = _reported(ctx, history, effect)
    pinned = tuple(
        ReachableCondition(number=override.condition_number, pinned_variant=override.variant, variant_property=None)
        for override in removed
        if override.condition_number is not None and override.same_audience
    )
    if not pinned:
        return None
    return pinned_conditions(pinned, flag.variants, all_counted=len(pinned) == len(removed))


def _reported(ctx: HealthContext, history: FlagHistory, effect: ConditionsNetEffect) -> list[RemovedOverride]:
    # An excluded variant is not in the results, so an override to it biased nothing. An override that changed and
    # changed back while nobody was exposed moved nobody.
    return [
        override
        for override in effect.overrides.removed
        if override.variant not in ctx.excluded_variant_keys
        and ((window := override.temporary_window) is None or history.exposed_during_overrides.get(window) is not False)
    ]


def _override_removed(
    ctx: HealthContext, history: FlagHistory, effect: ConditionsNetEffect, removed: list[RemovedOverride]
) -> ExperimentHealthFinding | None:
    pins = removed_overrides_to_grade(ctx)
    grade = grade_pinned_share(pins, ctx.condition_set_traffic) if pins is not None and pins.weighted else None
    severity = pinned_share_severity(grade)
    if not removed:
        return None
    if severity is None:
        # A pin to a variant with 0% in the split was the only source of that variant's results, however few.
        if pins is None or not pins.unweighted:
            return None
        severity = ExperimentHealthFindingSeverity.INFO
    subcode = (
        ConditionsChangeShape.REVERTED
        if effect.shape == ConditionsChangeShape.REVERTED
        else ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED
    )
    what_changed = [_removed(override, history.team_timezone) for override in removed]
    few = few_exposed_units(history, ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS)
    if severity == ExperimentHealthFindingSeverity.WARNING and few is not None:
        return _finding(
            history,
            effect,
            subcode=subcode,
            title=_OVERRIDE_TITLE,
            severity=ExperimentHealthFindingSeverity.INFO,
            sentences=[
                *what_changed,
                exposed_when(history, effect, few),
                *leave_out(history, effect, few),
                *_measured(grade, removed),
            ],
            grade=grade,
            diagnostic_ref="A7",
        )
    last_changed_at = max(override.restored_at or override.removed_at for override in removed)
    return _finding(
        history,
        effect,
        subcode=subcode,
        title=_OVERRIDE_TITLE,
        severity=severity,
        sentences=[
            *what_changed,
            *_moved(removed),
            *_measured(grade, removed),
            f"Reset the experiment, or move its start date to "
            f"{suggested_start(last_changed_at, history.team_timezone)}.",
        ],
        grade=grade,
        diagnostic_ref="A7",
    )


def _moved(removed: list[RemovedOverride]) -> list[str]:
    if len(removed) == 1 and removed[0].restored_at is not None:
        return [
            f'Between these changes, users it matches did not get "{removed[0].variant}", so those exposed then may '
            "have switched variants. Their exposures stay in the results."
        ]
    if any(override.restored_at is not None for override in removed):
        return [
            "For a while, users they match did not get the override's variant, so those exposed then may have "
            "switched variants. Their exposures stay in the results."
        ]
    if len(removed) == 1:
        variant = f'"{removed[0].variant}"'
        return [
            f"Users it matched got {variant} while the override was in place and a random variant after, so those "
            f"exposed while it was in place may have switched variants. Their exposures under {variant} stay in the "
            "results."
        ]
    return [
        "Users they matched got the override's variant while it was in place and a random variant after, so those "
        "exposed while it was in place may have switched variants. Their exposures stay in the results."
    ]


def _removed(override: RemovedOverride, team_timezone: str) -> str:
    removed_at = format_change_time(override.removed_at, team_timezone)
    if override.restored_at is not None:
        restored_at = format_change_time(override.restored_at, team_timezone)
        return (
            f'The variant override "{override.variant}" of Set {override.condition_number} changed on {removed_at} '
            f"and was set back on {restored_at}."
        )
    set_at = format_change_time(override.set_at, team_timezone) if override.set_at is not None else None
    if override.condition_number is None:
        subject = f'A release condition with the variant override "{override.variant}"'
        set_verb = "added"
    else:
        subject = f'The variant override "{override.variant}" of Set {override.condition_number}'
        set_verb = "set"
    if set_at is None:
        return f"{subject} was removed on {removed_at}."
    return f"{subject} was {set_verb} on {set_at} and removed on {removed_at}."


def _measured(grade: PinnedShareGrade | None, removed: list[RemovedOverride]) -> list[str]:
    single = len(removed) == 1 and removed[0].condition_number is not None
    subject = f"Set {removed[0].condition_number}" if single else "these conditions"
    matches = "matches" if single else "match"
    measurement = grade.measurement if grade is not None else None
    if grade is not None and grade.share is not None and measurement is not None:
        since = format_change_time(measurement.since, measurement.team_timezone)
        return [
            f"Since {since}, {subject} matched about {percent(grade.share)} of the users who would get "
            f'"{measurement.most_pinned_variant}" with the override in place ({measurement.pinned_people:,} of '
            f"about {round(measurement.variant_people):,})."
        ]
    if grade is None:
        return [
            f"PostHog can't measure how many users {'the override' if len(removed) == 1 else 'the overrides'} matched."
        ]
    if grade.unknown_reason == PinnedShareUnknownReason.EVALUATED_OUTSIDE_FLAG_SERVICE:
        return [
            "Most of this flag's calls are evaluated locally in a server SDK, bootstrapped, or assigned in your own "
            f"code, so PostHog can't measure how many users {subject} {matches}."
        ]
    if grade.unknown_reason == PinnedShareUnknownReason.TOO_FEW_PEOPLE and measurement is not None:
        since = format_change_time(measurement.since, measurement.team_timezone)
        return [f"Too few users called the flag since {since} to measure how many users {subject} {matches}."]
    return [f"PostHog can't measure how many users {subject} {matches}."]


def _finding(
    history: FlagHistory,
    effect: ConditionsNetEffect,
    *,
    subcode: ConditionsChangeShape,
    title: str,
    sentences: list[str],
    severity: ExperimentHealthFindingSeverity = ExperimentHealthFindingSeverity.INFO,
    grade: PinnedShareGrade | None = None,
    diagnostic_ref: str = "A6",
) -> ExperimentHealthFinding:
    return change_finding(
        history,
        effect,
        kind=ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS,
        code=ExperimentHealthFindingCode.RELEASE_CONDITIONS_CHANGED_MID_RUN,
        subcode=subcode.value,
        severity=severity,
        title=title,
        sentences=sentences,
        kind_evidence={**_kind_evidence(effect), **(grade.evidence() if grade is not None else {})},
        diagnostic_ref=diagnostic_ref,
    )


def _not_checked(history: FlagHistoryNotChecked) -> ExperimentHealthFinding | None:
    effect = conditions_net_effect(changes_not_checked(history, ConditionsChange), current=None)
    if effect is None:
        return None
    return not_checked_finding(
        history,
        effect,
        code=ExperimentHealthFindingCode.RELEASE_CONDITIONS_CHANGED_MID_RUN,
        title=_NOT_CHECKED_TITLE,
        what_changed=[f"{_changed(history, effect)}{_condition_counts(effect)}."],
        kind_evidence=_kind_evidence(effect),
        diagnostic_ref=_diagnostic_ref(effect),
    )


def _changed(history: FlagHistory | FlagHistoryNotChecked, effect: ConditionsNetEffect) -> str:
    first_at = format_change_time(effect.first.changed_at, history.team_timezone)
    if effect.change_count == 1:
        return f"The release conditions changed on {first_at}"
    last_at = format_change_time(effect.last.changed_at, history.team_timezone)
    return f"The release conditions changed {effect.change_count} times between {first_at} and {last_at}"


def _set_back(history: FlagHistory, effect: ConditionsNetEffect) -> str:
    first_at = format_change_time(effect.first.changed_at, history.team_timezone)
    last_at = format_change_time(effect.last.changed_at, history.team_timezone)
    if effect.change_count == 2:
        return f"The release conditions changed on {first_at} and were set back on {last_at}."
    return (
        f"The release conditions changed {effect.change_count} times between {first_at} and {last_at}, and the "
        "last change set them back."
    )


def _condition_counts(effect: ConditionsNetEffect) -> str:
    before = len(effect.from_conditions)
    after = len(effect.to_conditions)
    if before == after:
        return ""
    return f", from {before} {_conditions(before)} to {after} {_conditions(after)}"


def _conditions(count: int) -> str:
    return "condition" if count == 1 else "conditions"


def _diagnostic_ref(effect: ConditionsNetEffect) -> str:
    return "A7" if effect.shape == ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED else "A6"


def _kind_evidence(effect: ConditionsNetEffect) -> dict[str, int]:
    return {"conditions_before": len(effect.from_conditions), "conditions_after": len(effect.to_conditions)}
