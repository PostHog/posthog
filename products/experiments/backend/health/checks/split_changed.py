"""
A variant split of the experiment's flag that changed after launch while people were already exposed. Pure
functions, no I/O: `health/exposure_gate.py` loads the changes and the exposure answers.

People exposed before such a change can get another variant after it, so the results mix two assignments.
"""

from datetime import UTC, timedelta
from typing import Literal

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.flag_state import is_single_variant_shipped
from products.experiments.backend.health.context import (
    FlagState,
    HealthContext,
    SplitHistory,
    SplitHistoryNotChecked,
    SplitHistoryNotCheckedReason,
)
from products.experiments.backend.health.split_changes import (
    SplitChangeShape,
    SplitNetEffect,
    added_variant_keys,
    describe_split,
    format_change_time,
    net_effect,
    removed_variant_keys,
    rolled_out_variant_key,
    zeroed_variant_keys,
)

# pinned: the subcode of a split history that was not checked against the exposures. The page sends it as
# `finding_variant` on the health finding events.
NOT_CHECKED = "not_checked"

_TITLE = "The variant split changed after launch"
_REVERTED_INFO_TITLE = "The variant split changed and was set back"
_NOT_CHECKED_TITLE = "Variant split changes were not checked"
_HISTORY_NOT_CHECKED_TITLE = "The variant split history was not checked"
_SECONDS_PER_DAY = 24 * 60 * 60


def split_changed_mid_run(ctx: HealthContext) -> ExperimentHealthFinding | None:
    history = ctx.split_history
    flag = ctx.flag
    if history is None or flag is None or flag.deleted or not ctx.is_running or ctx.archived:
        return None
    # `flag_variants_mismatch` reports a flag without variants, and the variants have to come back first.
    if not any(variant.key for variant in flag.variants):
        return None
    if isinstance(history, SplitHistoryNotChecked):
        return _not_checked(history, flag)
    effect = net_effect(history.counted_changes)
    if effect is None or _reported_as_shipped(effect, flag):
        return None

    if effect.shape == SplitChangeShape.REVERTED and history.exposed_between is False:
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.INFO,
            title=_REVERTED_INFO_TITLE,
            sentences=[*_reverted(history, effect), "Nobody was exposed in between."],
        )
    if effect.shape == SplitChangeShape.REVERTED:
        start_at = _suggested_start(history, effect)
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.WARNING,
            title=_TITLE,
            sentences=[
                *_reverted(history, effect),
                *_delay(history, effect),
                "People exposed in between may have switched variants.",
                f"Move the start date to {start_at}, or reset the experiment.",
            ],
        )
    return _finding(
        history,
        effect,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=_TITLE,
        sentences=[
            _what_changed(history, effect),
            *_delay(history, effect),
            *_consequence(history, effect),
            f"A sample ratio mismatch or users in more than one variant can come from {_the_change(effect, 'this')}.",
        ],
    )


def _not_checked(history: SplitHistoryNotChecked, flag: FlagState) -> ExperimentHealthFinding | None:
    if history.reason == SplitHistoryNotCheckedReason.NO_HISTORY_ACCESS:
        return ExperimentHealthFinding(
            code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
            subcode=NOT_CHECKED,
            severity=ExperimentHealthFindingSeverity.INFO,
            title=_HISTORY_NOT_CHECKED_TITLE,
            detail=(
                "This check can't see whether the variant split changed after launch, because "
                f"{_not_checked_because(history.reason)}. Viewing the history needs viewer access to the flag and, "
                "with an API key, the activity_log:read scope."
            ),
            evidence={"reason": history.reason.value},
            # The flag history is the page this caller can't open.
            actions=(),
            diagnostic_ref="E3",
        )
    effect = net_effect(history.changes)
    if effect is None or _reported_as_shipped(effect, flag):
        return None
    the_change = _the_change(effect, "the")
    at = format_change_time(effect.last.changed_at, history.team_timezone)
    from_split = describe_split(effect.from_split)
    if effect.shape == SplitChangeShape.REVERTED:
        what_changed = (
            f"The variant split changed {effect.change_count} times after launch and was set back to "
            f"{from_split} on {at}."
        )
    elif effect.change_count > 1:
        what_changed = (
            f"The variant split changed {effect.change_count} times after launch, from {from_split} to "
            f"{describe_split(effect.to_split)}, last on {at}."
        )
    else:
        what_changed = f"The variant split changed from {from_split} to {describe_split(effect.to_split)} on {at}."
    next_step = (
        f"Add the query:read scope to this API key, or review {the_change} in the flag history."
        if history.reason == SplitHistoryNotCheckedReason.NO_QUERY_ACCESS
        else f"Review {the_change} in the flag history."
    )
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
        subcode=NOT_CHECKED,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=_NOT_CHECKED_TITLE,
        detail=" ".join(
            [
                what_changed,
                f"This check can't tell whether anyone was exposed before {the_change}, because "
                f"{_not_checked_because(history.reason)}.",
                next_step,
            ]
        ),
        evidence={"reason": history.reason.value, **_change_evidence(history, effect, exposed_before_change=None)},
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref="E3",
    )


def _not_checked_because(reason: SplitHistoryNotCheckedReason) -> str:
    match reason:
        case SplitHistoryNotCheckedReason.EXPOSURE_FILTERS:
            return "the exposure criteria filter by properties"
        case SplitHistoryNotCheckedReason.EXPOSURE_ACTION:
            return "exposures come from an action"
        case SplitHistoryNotCheckedReason.EXPOSURE_CRITERIA:
            return "the exposure criteria can't be read"
        case SplitHistoryNotCheckedReason.NO_QUERY_ACCESS:
            return "this API key can't query events"
        case SplitHistoryNotCheckedReason.NO_HISTORY_ACCESS:
            return "you can't view the linked feature flag's history"


def _reported_as_shipped(effect: SplitNetEffect, flag: FlagState) -> bool:
    # `variant_shipped_while_running` reports this state, and its detail carries the date of the rollout.
    return effect.shape == SplitChangeShape.VARIANT_ROLLED_OUT and is_single_variant_shipped(flag)


def _what_changed(history: SplitHistory, effect: SplitNetEffect) -> str:
    from_split = describe_split(effect.from_split)
    to_split = describe_split(effect.to_split)
    at = format_change_time(effect.last.changed_at, history.team_timezone)
    if effect.change_count > 1:
        # Changes before the first exposure are not counted, so the count names its own span. "Since launch"
        # would undercount what the flag history shows.
        first_at = format_change_time(effect.first.changed_at, history.team_timezone)
        return (
            f"The split changed {effect.change_count} times between {first_at} and {at}, "
            f"from {from_split} to {to_split}."
        )
    match effect.shape:
        case SplitChangeShape.VARIANT_ROLLED_OUT:
            variant = _rolled_out_variant(effect, starts_sentence=True)
            return f"{variant} was set to 100% of the split on {at}, while the experiment is still running."
        case SplitChangeShape.VARIANT_REMOVED:
            keys = removed_variant_keys(effect.from_split, effect.to_split)
            return f"{_variants(keys)} {_was(keys)} removed on {at} (from {from_split} to {to_split})."
        case SplitChangeShape.VARIANT_ADDED:
            keys = added_variant_keys(effect.from_split, effect.to_split)
            return f"{_variants(keys)} {_was(keys)} added on {at} (from {from_split} to {to_split})."
        case SplitChangeShape.VARIANT_ZEROED:
            keys = zeroed_variant_keys(effect.from_split, effect.to_split)
            return f"{_variants(keys)} {_was(keys)} set to 0% on {at} (from {from_split} to {to_split})."
        case SplitChangeShape.REORDERED:
            return f"The order of the variants changed on {at} (from {from_split} to {to_split})."
        case _:
            return f"The split changed from {from_split} to {to_split} on {at}."


def _consequence(history: SplitHistory, effect: SplitNetEffect) -> list[str]:
    start_at = _suggested_start(history, effect)
    the_change = _the_change(effect, "the")
    match effect.shape:
        case SplitChangeShape.VARIANT_ROLLED_OUT:
            variant = _rolled_out_variant(effect, starts_sentence=False)
            return [
                f"From then on, the split assigns everyone to {variant}.",
                "End the experiment with a conclusion, or restore the split.",
            ]
        case SplitChangeShape.VARIANT_REMOVED:
            keys = _quoted(removed_variant_keys(effect.from_split, effect.to_split), conjunction="or")
            return [
                f"The results leave out people who saw only {keys}, and people who had {keys} may now get "
                "another variant.",
                f"Reset the experiment, or move its start date to {start_at}.",
            ]
        case SplitChangeShape.VARIANT_ADDED:
            return [
                f"People exposed before {the_change} may have switched variants.",
                f"Reset the experiment, or move its start date to {start_at}.",
            ]
        case SplitChangeShape.VARIANT_ZEROED:
            # The zeroed share goes to other variants, which moves their boundaries too. Excluding the zeroed
            # variant from the analysis therefore leaves mixed assignments in the variants that remain.
            keys = _quoted(zeroed_variant_keys(effect.from_split, effect.to_split), conjunction="and")
            return [
                f"People exposed before {the_change} may have switched variants, and no new users get {keys}.",
                f"Reset the experiment, or move its start date to {start_at}.",
            ]
        case SplitChangeShape.REORDERED:
            # Restoring the order moves the people exposed since the change a second time.
            return [
                f"The order decides who gets which variant, so people exposed before {the_change} may have "
                "switched variants.",
                f"Reset the experiment, or move its start date to {start_at}.",
            ]
        case _:
            return [
                f"People exposed before {the_change} may have switched variants, so the results mix two assignments.",
                f"Reset the experiment, or move its start date to {start_at} to analyze only the people exposed "
                f"after {the_change}.",
            ]


def _reverted(history: SplitHistory, effect: SplitNetEffect) -> list[str]:
    first_at = format_change_time(effect.first.changed_at, history.team_timezone)
    last_at = format_change_time(effect.last.changed_at, history.team_timezone)
    from_split = describe_split(effect.from_split)
    if effect.change_count > 2:
        return [
            f"The split changed {effect.change_count} times between {first_at} and {last_at}, "
            f"and was set back to {from_split}."
        ]
    changed_to = describe_split(effect.first.after)
    if history.exposed_between is False:
        span = _duration((effect.last.changed_at - effect.first.changed_at).total_seconds())
        return [f"The split was set to {changed_to} on {first_at} and set back {span} later."]
    return [f"The split was set to {changed_to} on {first_at} and set back to {from_split} on {last_at}."]


def _delay(history: SplitHistory, effect: SplitNetEffect) -> list[str]:
    # When nobody knows whether anyone was exposed before the change, or the change came days after launch,
    # the time since launch tells the reader how many people the change can have moved.
    seconds = _seconds_after_launch(history, effect)
    if history.exposed_before_first is not None and seconds <= _SECONDS_PER_DAY:
        return []
    change = "The change" if effect.change_count == 1 else "The first change"
    return [f"{change} came {_duration(seconds)} after launch."]


def _finding(
    history: SplitHistory,
    effect: SplitNetEffect,
    *,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    sentences: list[str],
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
        subcode=effect.shape.value,
        severity=severity,
        title=title,
        detail=" ".join(sentences),
        evidence=_change_evidence(history, effect, exposed_before_change=history.exposed_before_first),
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref=(
            "E4" if effect.shape in (SplitChangeShape.VARIANT_ADDED, SplitChangeShape.VARIANT_REMOVED) else "E3"
        ),
    )


def _change_evidence(
    history: SplitHistory | SplitHistoryNotChecked, effect: SplitNetEffect, *, exposed_before_change: bool | None
) -> dict[str, str | int | bool | None]:
    return {
        "change_count": effect.change_count,
        "first_changed_at": effect.first.changed_at.astimezone(UTC).isoformat(),
        "last_changed_at": effect.last.changed_at.astimezone(UTC).isoformat(),
        "from": describe_split(effect.from_split),
        "to": describe_split(effect.to_split),
        "exposed_before_change": exposed_before_change,
        "seconds_after_launch": int(_seconds_after_launch(history, effect)),
    }


def _suggested_start(history: SplitHistory, effect: SplitNetEffect) -> str:
    # The start date picker saves whole minutes, so a start inside the minute of the change keeps exposures
    # from before it.
    changed_at = effect.last.changed_at
    minute = changed_at.replace(second=0, microsecond=0)
    start = minute if minute == changed_at else minute + timedelta(minutes=1)
    return format_change_time(start, history.team_timezone)


def _seconds_after_launch(history: SplitHistory | SplitHistoryNotChecked, effect: SplitNetEffect) -> float:
    return (effect.first.changed_at - history.launched_at).total_seconds()


def _the_change(effect: SplitNetEffect, determiner: Literal["the", "this"]) -> str:
    if effect.change_count == 1:
        return f"{determiner} change"
    return "the changes" if determiner == "the" else "these changes"


def _rolled_out_variant(effect: SplitNetEffect, *, starts_sentence: bool) -> str:
    key = rolled_out_variant_key(effect.to_split)
    if key:
        return f'{"Variant" if starts_sentence else "variant"} "{key}"'
    return "One variant" if starts_sentence else "one variant"


def _was(keys: list[str]) -> str:
    return "was" if len(keys) == 1 else "were"


def _variants(keys: list[str]) -> str:
    noun = "Variant" if len(keys) == 1 else "Variants"
    return f"{noun} {_quoted(keys, conjunction='and')}"


def _quoted(keys: list[str], *, conjunction: Literal["and", "or"]) -> str:
    quoted = [f'"{key}"' for key in keys]
    if len(quoted) <= 1:
        return "".join(quoted)
    return f"{', '.join(quoted[:-1])} {conjunction} {quoted[-1]}"


def _duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return _count(minutes, "minute")
    hours = minutes // 60
    if hours < 48:
        return _count(hours, "hour")
    return _count(hours // 24, "day")


def _count(value: int, unit: str) -> str:
    return f"{value} {unit}" if value == 1 else f"{value} {unit}s"
