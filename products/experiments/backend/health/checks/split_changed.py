"""
A variant split of the experiment's flag that changed after launch while people were already exposed. Pure
functions, no I/O: `health/exposure_gate.py` loads the changes and the exposure answers.

People exposed before such a change can get another variant after it, so the results mix two assignments.
"""

from datetime import UTC
from typing import Literal

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.change_wording import (
    delay,
    duration,
    not_checked_because,
    not_checked_next_step,
    suggested_start,
    the_change,
)
from products.experiments.backend.health.checks.flag_state import is_single_variant_shipped
from products.experiments.backend.health.context import (
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    FlagState,
    HealthContext,
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
_HISTORY_NOT_CHECKED_TITLE = "The flag history was not checked"


def split_changed_mid_run(ctx: HealthContext) -> ExperimentHealthFinding | None:
    history = ctx.flag_history
    flag = ctx.flag
    if history is None or flag is None or flag.deleted or not ctx.is_running or ctx.archived:
        return None
    # `flag_variants_mismatch` reports a flag without variants, and the variants have to come back first.
    if not any(variant.key for variant in flag.variants):
        return None
    if isinstance(history, FlagHistoryNotChecked):
        return _not_checked(history, flag)
    effect = net_effect(history.counted_split_changes)
    if effect is None or _reported_as_shipped(effect, flag):
        return None

    if effect.shape == SplitChangeShape.REVERTED and history.split_exposed_between is False:
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.INFO,
            title=_REVERTED_INFO_TITLE,
            sentences=[*_reverted(history, effect), "Nobody was exposed in between."],
        )
    if effect.shape == SplitChangeShape.REVERTED:
        start_at = suggested_start(effect.last.changed_at, history.team_timezone)
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
            "A sample ratio mismatch or users in more than one variant can come from "
            f"{the_change(effect.change_count, 'this')}.",
        ],
    )


def _not_checked(history: FlagHistoryNotChecked, flag: FlagState) -> ExperimentHealthFinding | None:
    # This finding speaks for the bucketing and release-condition checks too, because none of them can read the
    # history for this reason.
    if history.reason == FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS:
        return ExperimentHealthFinding(
            code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
            subcode=NOT_CHECKED,
            severity=ExperimentHealthFindingSeverity.INFO,
            title=_HISTORY_NOT_CHECKED_TITLE,
            detail=(
                "This check can't see whether the flag's variant split, key, bucketing or release conditions "
                f"changed after launch, because {not_checked_because(history.reason)}. Viewing the history needs "
                "viewer access to the flag and, with an API key, the activity_log:read scope."
            ),
            evidence={"reason": history.reason.value},
            # The flag history is the page this caller can't open.
            actions=(),
            diagnostic_ref="E3",
        )
    effect = net_effect(history.split_changes)
    if effect is None or _reported_as_shipped(effect, flag):
        return None
    change = the_change(effect.change_count, "the")
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
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
        subcode=NOT_CHECKED,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=_NOT_CHECKED_TITLE,
        detail=" ".join(
            [
                what_changed,
                f"This check can't tell whether anyone was exposed before {change}, because "
                f"{not_checked_because(history.reason)}.",
                not_checked_next_step(history.reason, change),
            ]
        ),
        evidence={"reason": history.reason.value, **_change_evidence(history, effect, exposed_before_change=None)},
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref="E3",
    )


def _reported_as_shipped(effect: SplitNetEffect, flag: FlagState) -> bool:
    # `variant_shipped_while_running` reports this state, and its detail carries the date of the rollout.
    return effect.shape == SplitChangeShape.VARIANT_ROLLED_OUT and is_single_variant_shipped(flag)


def _what_changed(history: FlagHistory, effect: SplitNetEffect) -> str:
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


def _consequence(history: FlagHistory, effect: SplitNetEffect) -> list[str]:
    start_at = suggested_start(effect.last.changed_at, history.team_timezone)
    change = the_change(effect.change_count, "the")
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
                f"People exposed before {change} may have switched variants.",
                f"Reset the experiment, or move its start date to {start_at}.",
            ]
        case SplitChangeShape.VARIANT_ZEROED:
            # The zeroed share goes to other variants, which moves their boundaries too. Excluding the zeroed
            # variant from the analysis therefore leaves mixed assignments in the variants that remain.
            keys = _quoted(zeroed_variant_keys(effect.from_split, effect.to_split), conjunction="and")
            return [
                f"People exposed before {change} may have switched variants, and no new users get {keys}.",
                f"Reset the experiment, or move its start date to {start_at}.",
            ]
        case SplitChangeShape.REORDERED:
            # Restoring the order moves the people exposed since the change a second time.
            return [
                f"The order decides who gets which variant, so people exposed before {change} may have "
                "switched variants.",
                f"Reset the experiment, or move its start date to {start_at}.",
            ]
        case _:
            return [
                f"People exposed before {change} may have switched variants, so the results mix two assignments.",
                f"Reset the experiment, or move its start date to {start_at} to analyze only the people exposed "
                f"after {change}.",
            ]


def _reverted(history: FlagHistory, effect: SplitNetEffect) -> list[str]:
    first_at = format_change_time(effect.first.changed_at, history.team_timezone)
    last_at = format_change_time(effect.last.changed_at, history.team_timezone)
    from_split = describe_split(effect.from_split)
    if effect.change_count > 2:
        return [
            f"The split changed {effect.change_count} times between {first_at} and {last_at}, "
            f"and was set back to {from_split}."
        ]
    changed_to = describe_split(effect.first.after)
    if history.split_exposed_between is False:
        span = duration((effect.last.changed_at - effect.first.changed_at).total_seconds())
        return [f"The split was set to {changed_to} on {first_at} and set back {span} later."]
    return [f"The split was set to {changed_to} on {first_at} and set back to {from_split} on {last_at}."]


def _delay(history: FlagHistory, effect: SplitNetEffect) -> list[str]:
    return delay(
        launched_at=history.launched_at,
        first_changed_at=effect.first.changed_at,
        exposed_before_first=history.exposed_before_first,
        change_count=effect.change_count,
    )


def _finding(
    history: FlagHistory,
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
    history: FlagHistory | FlagHistoryNotChecked, effect: SplitNetEffect, *, exposed_before_change: bool | None
) -> dict[str, str | int | bool | None]:
    return {
        "change_count": effect.change_count,
        "first_changed_at": effect.first.changed_at.astimezone(UTC).isoformat(),
        "last_changed_at": effect.last.changed_at.astimezone(UTC).isoformat(),
        "from": describe_split(effect.from_split),
        "to": describe_split(effect.to_split),
        "exposed_before_change": exposed_before_change,
        "seconds_after_launch": int((effect.first.changed_at - history.launched_at).total_seconds()),
    }


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
