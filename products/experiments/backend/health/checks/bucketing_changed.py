"""
A flag setting that decides the variant draw changed after launch while people were already exposed: the key, the
group type the flag matches by, the bucketing identifier, or persistence across authentication. Pure functions, no
I/O: `health/exposure_gate.py` loads the changes and the exposure answers.

People exposed before such a change get a new draw, so they can get another variant after it. When fewer than
MIN_EXPOSED_UNITS_TO_WARN were exposed before the last change, that can't move the results, so it is info.
"""

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
)
from products.experiments.backend.health.bucketing_changes import (
    BucketingChangeShape,
    BucketingNetEffect,
    bucketing_net_effect,
    describe_bucketing_value,
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
from products.experiments.backend.health.context import FlagHistory, FlagHistoryNotChecked, HealthContext
from products.experiments.backend.health.skips import CheckOutcome, CheckSkip
from products.experiments.backend.health.split_changes import format_change_time
from products.feature_flags.backend.facade.edits import BucketingChange, BucketingSetting

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


def bucketing_changed_mid_run(ctx: HealthContext) -> CheckOutcome:
    history = changes_to_check(ctx)
    if isinstance(history, CheckSkip):
        return history
    if isinstance(history, FlagHistoryNotChecked):
        return _not_checked(history)
    effect = bucketing_net_effect(history.counted(BucketingChange))
    if effect is None:
        return None

    few = few_exposed_units(history, ExperimentHealthFlagChangeKind.BUCKETING)
    if effect.shape == BucketingChangeShape.REVERTED:
        first_at = format_change_time(effect.first.changed_at, history.team_timezone)
        changed = _changed_settings(effect)
        if history.exposed_between.get(ExperimentHealthFlagChangeKind.BUCKETING) is False:
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
        set_back = f"{changed} changed on {first_at} and {_was(effect)} set back on {last_at}."
        if few is not None:
            return _finding(
                history,
                effect,
                severity=ExperimentHealthFindingSeverity.INFO,
                title=_TITLE,
                sentences=[set_back, exposed_when(history, effect, few), *leave_out(history, effect, few)],
            )
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.WARNING,
            title=_TITLE,
            sentences=[
                set_back,
                *delay_after_launch(history, effect),
                "People exposed in between got a new variant draw, so they may have switched variants.",
                f"Move the start date to {suggested_start(effect.last.changed_at, history.team_timezone)}, or "
                "reset the experiment.",
            ],
        )

    title = _KEY_TITLE if effect.shape == BucketingChangeShape.KEY_CHANGED else _TITLE
    what_changed = [_what_changed(net, history.team_timezone) for net in effect.net_changes]
    if few is not None:
        return _finding(
            history,
            effect,
            severity=ExperimentHealthFindingSeverity.INFO,
            title=title,
            sentences=[
                *what_changed,
                exposed_when(history, effect, few),
                *leave_out(history, effect, few),
                *_key_state(effect),
            ],
        )
    start_at = suggested_start(effect.last.changed_at, history.team_timezone)
    return _finding(
        history,
        effect,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title=title,
        sentences=[
            *what_changed,
            *delay_after_launch(history, effect),
            *_consequence(effect),
            f"Reset the experiment, or move its start date to {start_at}.",
        ],
    )


def _not_checked(history: FlagHistoryNotChecked) -> ExperimentHealthFinding | None:
    effect = bucketing_net_effect(history.of_kind(BucketingChange))
    if effect is None:
        return None
    if effect.shape == BucketingChangeShape.REVERTED:
        at = format_change_time(effect.last.changed_at, history.team_timezone)
        what_changed = [f"{_changed_settings(effect)} changed after launch and {_was(effect)} set back on {at}."]
    else:
        what_changed = [_what_changed(net, history.team_timezone) for net in effect.net_changes]
    return not_checked_finding(
        history,
        effect,
        code=ExperimentHealthFindingCode.BUCKETING_CHANGED_MID_RUN,
        title=_NOT_CHECKED_TITLE,
        what_changed=what_changed,
        kind_evidence=_kind_evidence(effect),
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


def _key_state(effect: BucketingNetEffect) -> list[str]:
    if effect.shape != BucketingChangeShape.KEY_CHANGED:
        return []
    key = next(change for change in effect.net_changes if change.setting == BucketingSetting.KEY)
    return [
        f"Code that still uses {describe_bucketing_value(BucketingSetting.KEY, key.before)} no longer gets this flag."
    ]


def _changed_settings(effect: BucketingNetEffect) -> str:
    names = list(dict.fromkeys(_SETTING_NAMES[setting] for setting in effect.changed_settings))
    joined = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    return joined[0].upper() + joined[1:]


def _was(effect: BucketingNetEffect) -> str:
    return "was" if len({_SETTING_NAMES[setting] for setting in effect.changed_settings}) == 1 else "were"


def _finding(
    history: FlagHistory,
    effect: BucketingNetEffect,
    *,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    sentences: list[str],
) -> ExperimentHealthFinding:
    return change_finding(
        history,
        effect,
        kind=ExperimentHealthFlagChangeKind.BUCKETING,
        code=ExperimentHealthFindingCode.BUCKETING_CHANGED_MID_RUN,
        subcode=effect.shape.value,
        severity=severity,
        title=title,
        sentences=sentences,
        kind_evidence=_kind_evidence(effect),
        diagnostic_ref="A6",
    )


def _kind_evidence(effect: BucketingNetEffect) -> dict[str, str]:
    return {"changed_settings": ",".join(effect.changed_settings)}
