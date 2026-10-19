"""
A flag setting that decides the variant draw changed after launch while people were already exposed: the key, the
group type the flag matches by, the bucketing identifier, or persistence across authentication. Pure functions, no
I/O: `health/exposure_gate.py` loads the changes and the exposure answers.

People exposed before such a change get a new draw, so they can get another variant after it.
"""

from datetime import UTC

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.bucketing_changes import (
    BucketingChangeShape,
    BucketingNetEffect,
    bucketing_net_effect,
    describe_bucketing_value,
)
from products.experiments.backend.health.checks.change_wording import (
    delay,
    duration,
    not_checked_because,
    not_checked_next_step,
    suggested_start,
    the_change,
)
from products.experiments.backend.health.checks.split_changed import NOT_CHECKED
from products.experiments.backend.health.context import (
    BucketingChange,
    BucketingSetting,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagHistoryNotCheckedReason,
    HealthContext,
)
from products.experiments.backend.health.split_changes import format_change_time

_TITLE = "The flag's variant assignment changed after launch"
_KEY_TITLE = "The flag key changed after launch"
_REVERTED_INFO_TITLE = "The flag's variant assignment changed and was set back"
_NOT_CHECKED_TITLE = "Variant assignment changes were not checked"

_SETTING_NAMES = {
    BucketingSetting.KEY: "the flag key",
    BucketingSetting.AGGREGATION: 'the flag\'s "Match by" setting',
    BucketingSetting.BUCKETING_IDENTIFIER: 'the flag\'s "Match by" setting',
    BucketingSetting.EXPERIENCE_CONTINUITY: 'the flag\'s "Persist flag across authentication steps" setting',
}


def bucketing_changed_mid_run(ctx: HealthContext) -> ExperimentHealthFinding | None:
    history = ctx.flag_history
    flag = ctx.flag
    if history is None or flag is None or flag.deleted or not ctx.is_running or ctx.archived:
        return None
    # `flag_variants_mismatch` reports a flag without variants, and the variants have to come back first.
    if not any(variant.key for variant in flag.variants):
        return None
    if isinstance(history, FlagHistoryNotChecked):
        return _not_checked(history)
    effect = bucketing_net_effect(history.counted_bucketing_changes)
    if effect is None:
        return None

    if effect.shape == BucketingChangeShape.REVERTED:
        first_at = format_change_time(effect.first.changed_at, history.team_timezone)
        changed = _changed_settings(effect)
        if history.bucketing_exposed_between is False:
            span = duration((effect.last.changed_at - effect.first.changed_at).total_seconds())
            return _finding(
                history,
                effect,
                severity=ExperimentHealthFindingSeverity.INFO,
                title=_REVERTED_INFO_TITLE,
                sentences=[
                    f"{changed} changed on {first_at} and {_was(effect)} set back {span} later.",
                    "Nobody was exposed in between.",
                ],
            )
        last_at = format_change_time(effect.last.changed_at, history.team_timezone)
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.WARNING,
            title=_TITLE,
            sentences=[
                f"{changed} changed on {first_at} and {_was(effect)} set back on {last_at}.",
                *_delay(history, effect),
                "People exposed in between got a new variant draw, so they may have switched variants.",
                f"Move the start date to {suggested_start(effect.last.changed_at, history.team_timezone)}, or "
                "reset the experiment.",
            ],
        )

    start_at = suggested_start(effect.last.changed_at, history.team_timezone)
    return _finding(
        history,
        effect,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=_KEY_TITLE if effect.shape == BucketingChangeShape.KEY_CHANGED else _TITLE,
        sentences=[
            *(_what_changed(net, history.team_timezone) for net in effect.net_changes),
            *_delay(history, effect),
            *_consequence(effect),
            f"Reset the experiment, or move its start date to {start_at}.",
        ],
    )


def _not_checked(history: FlagHistoryNotChecked) -> ExperimentHealthFinding | None:
    # `split_changed_mid_run` reports a history the reader can't view, for every kind of change.
    if history.reason == FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS:
        return None
    effect = bucketing_net_effect(history.bucketing_changes)
    if effect is None:
        return None
    change = the_change(effect.change_count, "the")
    if effect.shape == BucketingChangeShape.REVERTED:
        at = format_change_time(effect.last.changed_at, history.team_timezone)
        what_changed = [f"{_changed_settings(effect)} changed after launch and {_was(effect)} set back on {at}."]
    else:
        what_changed = [_what_changed(net, history.team_timezone) for net in effect.net_changes]
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.BUCKETING_CHANGED_MID_RUN,
        subcode=NOT_CHECKED,
        severity=ExperimentHealthFindingSeverity.INFO,
        title=_NOT_CHECKED_TITLE,
        detail=" ".join(
            [
                *what_changed,
                f"This check can't tell whether anyone was exposed before {change}, because "
                f"{not_checked_because(history.reason)}.",
                not_checked_next_step(history.reason, change),
            ]
        ),
        evidence={"reason": history.reason.value, **_evidence(history, effect, exposed_before_change=None)},
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref="A6",
    )


def _what_changed(change: BucketingChange, team_timezone: str) -> str:
    at = format_change_time(change.changed_at, team_timezone)
    before = describe_bucketing_value(change.setting, change.before)
    after = describe_bucketing_value(change.setting, change.after)
    match change.setting:
        case BucketingSetting.KEY:
            return f"The flag key changed from {before} to {after} on {at}."
        case BucketingSetting.AGGREGATION if change.before is not None and change.after is not None:
            return f"The flag changed to match by another group type on {at}."
        case BucketingSetting.AGGREGATION | BucketingSetting.BUCKETING_IDENTIFIER:
            return f"The flag changed from matching by {before} to matching by {after} on {at}."
        case BucketingSetting.EXPERIENCE_CONTINUITY:
            return f'"Persist flag across authentication steps" was turned {after} on {at}.'


def _consequence(effect: BucketingNetEffect) -> list[str]:
    match effect.shape:
        case BucketingChangeShape.KEY_CHANGED:
            key = next(change for change in effect.net_changes if change.setting == BucketingSetting.KEY)
            old_key = describe_bucketing_value(BucketingSetting.KEY, key.before)
            return [
                "The key is an input of the variant draw, so every user got a new one.",
                f"Exposures under {old_key} are no longer in the results, and code that still uses {old_key} no "
                "longer gets this flag.",
            ]
        case BucketingChangeShape.AGGREGATION_CHANGED:
            consequence = (
                "Every user and group got a new variant draw, so people exposed before "
                f"{the_change(effect.change_count, 'the')} may have switched variants."
            )
        case BucketingChangeShape.BUCKETING_IDENTIFIER_CHANGED:
            consequence = (
                "Users whose device ID differs from their user ID got a new variant draw, so they may have switched "
                "variants."
            )
        case _:
            consequence = "Users who logged in got a new variant draw, so they may have switched variants."
    return [
        consequence,
        "A sample ratio mismatch or users in more than one variant can come from "
        f"{the_change(effect.change_count, 'this')}.",
    ]


def _changed_settings(effect: BucketingNetEffect) -> str:
    names = list(dict.fromkeys(_SETTING_NAMES[setting] for setting in effect.changed_settings))
    joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return joined[0].upper() + joined[1:]


def _was(effect: BucketingNetEffect) -> str:
    return "was" if len({_SETTING_NAMES[setting] for setting in effect.changed_settings}) == 1 else "were"


def _delay(history: FlagHistory, effect: BucketingNetEffect) -> list[str]:
    return delay(
        launched_at=history.launched_at,
        first_changed_at=effect.first.changed_at,
        exposed_before_first=history.exposed_before_first,
        change_count=effect.change_count,
    )


def _finding(
    history: FlagHistory,
    effect: BucketingNetEffect,
    *,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    sentences: list[str],
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.BUCKETING_CHANGED_MID_RUN,
        subcode=effect.shape.value,
        severity=severity,
        title=title,
        detail=" ".join(sentences),
        evidence=_evidence(history, effect, exposed_before_change=history.exposed_before_first),
        actions=(ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
        diagnostic_ref="A6",
    )


def _evidence(
    history: FlagHistory | FlagHistoryNotChecked, effect: BucketingNetEffect, *, exposed_before_change: bool | None
) -> dict[str, str | int | bool | None]:
    return {
        "change_count": effect.change_count,
        "first_changed_at": effect.first.changed_at.astimezone(UTC).isoformat(),
        "last_changed_at": effect.last.changed_at.astimezone(UTC).isoformat(),
        "changed_settings": ",".join(effect.changed_settings),
        "exposed_before_change": exposed_before_change,
        "seconds_after_launch": int((effect.first.changed_at - history.launched_at).total_seconds()),
    }
