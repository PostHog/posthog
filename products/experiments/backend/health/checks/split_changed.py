"""
A variant split of the experiment's flag that changed after launch while people were already exposed. Pure
functions, no I/O: `health/exposure_gate.py` loads the changes and the exposure answers.

People exposed before such a change can get another variant after it, so the results mix two assignments. When
fewer than MIN_EXPOSED_UNITS_TO_WARN were exposed before the last change, that can't move the results, so it is info.
A variant rolled out to 100% stays a warning, because the split serves one variant from then on.
"""

from typing import Literal

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
)
from products.experiments.backend.health.checks.change_wording import duration, suggested_start, the_change
from products.experiments.backend.health.checks.flag_change_findings import (
    change_finding,
    changes_to_check,
    delay_after_launch,
    exposed_when,
    few_exposed_units,
    leave_out,
    not_checked_finding,
)
from products.experiments.backend.health.checks.flag_state import is_single_variant_shipped
from products.experiments.backend.health.context import FlagHistory, FlagHistoryNotChecked, FlagState, HealthContext
from products.experiments.backend.health.skips import CheckOutcome, CheckSkip
from products.experiments.backend.health.split_changes import (
    SplitChangeShape,
    SplitNetEffect,
    describe_split,
    format_change_time,
    net_effect,
)
from products.feature_flags.backend.facade.edits import (
    SplitChange,
    added_variant_keys,
    removed_variant_keys,
    rolled_out_variant_key,
    zeroed_variant_keys,
)

_TITLE = "The variant split changed after launch"
_REVERTED_INFO_TITLE = "The variant split changed and was set back"
_NOT_CHECKED_TITLE = "Variant split changes were not checked"


def split_changed_mid_run(ctx: HealthContext) -> CheckOutcome:
    history = changes_to_check(ctx)
    if isinstance(history, CheckSkip):
        return history
    flag = ctx.flag
    # `changes_to_check` skips an experiment without a flag, but the type doesn't carry that.
    if flag is None:
        return None
    if isinstance(history, FlagHistoryNotChecked):
        return _not_checked(history, flag)
    effect = net_effect(history.counted(SplitChange))
    if effect is None or _reported_as_shipped(effect, flag):
        return None

    if (
        effect.shape == SplitChangeShape.REVERTED
        and history.exposed_between.get(ExperimentHealthFlagChangeKind.SPLIT) is False
    ):
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.INFO,
            title=_REVERTED_INFO_TITLE,
            sentences=[*_reverted(history, effect), "Nobody was exposed in between."],
        )
    few = few_exposed_units(history, ExperimentHealthFlagChangeKind.SPLIT)
    # A variant at 100% serves everyone the same variant from then on, so the experiment compares nothing, however
    # few people were exposed before.
    if few is not None and effect.shape != SplitChangeShape.VARIANT_ROLLED_OUT:
        return _few_exposed(history, effect, few)
    if effect.shape == SplitChangeShape.REVERTED:
        start_at = suggested_start(effect.last.changed_at, history.team_timezone)
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.WARNING,
            title=_TITLE,
            sentences=[
                *_reverted(history, effect),
                *delay_after_launch(history, effect),
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
            *delay_after_launch(history, effect),
            *_consequence(history, effect),
            "A sample ratio mismatch or users in more than one variant can come from "
            f"{the_change(effect.change_count, 'this')}.",
        ],
    )


def _not_checked(history: FlagHistoryNotChecked, flag: FlagState) -> ExperimentHealthFinding | None:
    effect = net_effect(history.of_kind(SplitChange))
    if effect is None or _reported_as_shipped(effect, flag):
        return None
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
    return not_checked_finding(
        history,
        effect,
        code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
        title=_NOT_CHECKED_TITLE,
        what_changed=[what_changed],
        kind_evidence=_kind_evidence(effect),
        diagnostic_ref="E3",
    )


def _few_exposed(history: FlagHistory, effect: SplitNetEffect, count: int) -> ExperimentHealthFinding:
    what_changed = (
        _reverted(history, effect) if effect.shape == SplitChangeShape.REVERTED else [_what_changed(history, effect)]
    )
    from_then_on: list[str] = []
    if effect.shape == SplitChangeShape.VARIANT_ZEROED:
        keys = _quoted(zeroed_variant_keys(effect.from_split, effect.to_split), conjunction="and")
        from_then_on = [f"No new users get {keys}."]
    return _finding(
        history,
        effect,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=_TITLE,
        sentences=[
            *what_changed,
            exposed_when(history, effect, count),
            *leave_out(history, effect, count),
            *from_then_on,
        ],
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
    if history.exposed_between.get(ExperimentHealthFlagChangeKind.SPLIT) is False:
        span = duration((effect.last.changed_at - effect.first.changed_at).total_seconds())
        return [f"The split was set to {changed_to} on {first_at} and set back {span} later."]
    return [f"The split was set to {changed_to} on {first_at} and set back to {from_split} on {last_at}."]


def _finding(
    history: FlagHistory,
    effect: SplitNetEffect,
    *,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    sentences: list[str],
) -> ExperimentHealthFinding:
    return change_finding(
        history,
        effect,
        kind=ExperimentHealthFlagChangeKind.SPLIT,
        code=ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
        subcode=effect.shape.value,
        severity=severity,
        title=title,
        sentences=sentences,
        kind_evidence=_kind_evidence(effect),
        diagnostic_ref=(
            "E4" if effect.shape in (SplitChangeShape.VARIANT_ADDED, SplitChangeShape.VARIANT_REMOVED) else "E3"
        ),
    )


def _kind_evidence(effect: SplitNetEffect) -> dict[str, str]:
    return {"from": describe_split(effect.from_split), "to": describe_split(effect.to_split)}


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
