"""
Release conditions that override the variant. Pure functions, no I/O.

The flag service evaluates release conditions in their stored order, and the first match wins. A condition
whose variant override names one of the flag's variants serves that variant to the users it matches,
instead of the variant from the hash. An override that names no variant is ignored.
See `get_match` in rust/feature-flags/src/flags/flag_matching.rs and `pinned_variant` in flag_operations.rs.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.flag_state import is_single_variant_shipped, shipped_variant_key
from products.experiments.backend.health.condition_changes import conditions_net_effect
from products.experiments.backend.health.context import (
    ConditionsChange,
    ConditionSetTraffic,
    FlagHistory,
    HealthContext,
    ReachableCondition,
    Split,
)
from products.experiments.backend.health.split_changes import format_change_time

# pinned: the subcodes are sent as `finding_variant` on the health finding events, so insights group on them.
# Every condition that includes users pins a variant, so no user is randomly assigned. One variant gets
# everyone, or each variant gets a different group of users, so the results compare nothing valid.
ALL_CONDITIONS_PINNED = "all_conditions_pinned"
# Some conditions pin a variant. The users they match count in that variant's results without random
# assignment, so they bias the comparison unless the analysis excludes them, for example as test users.
SOME_CONDITIONS_PINNED = "some_conditions_pinned"

# The severity of SOME_CONDITIONS_PINNED follows the largest share that pinned users make up of one variant's users,
# in this window, or since launch or the flag's last save if later. The bias is per variant, so a few pinned users
# weigh more in a small variant. Below the first share they can't move a variant's results much, so there is no
# finding. Above the second they are a warning.
TRAFFIC_WINDOW = timedelta(days=7)
_NO_FINDING_BELOW_SHARE = 0.01
_WARNING_ABOVE_SHARE = 0.05
# With fewer people, the share of a few pinned people is mostly chance.
_MIN_MATCHED_PEOPLE = 100
# Only calls that the flag service evaluated name a condition set. When fewer calls than this share did, the
# pinned users can be among the calls that name none, so a share under the first threshold does not clear the
# finding. A share above it still counts, because the pinned users it found are real.
_MIN_REMOTELY_EVALUATED_SHARE_TO_CLEAR = 0.5


class PinnedShareUnknownReason(StrEnum):
    # pinned: the finding's `evidence.reason`, which the health finding events track.
    NOT_MEASURED = "not_measured"
    TOO_FEW_PEOPLE = "too_few_people"
    # Most calls carry no version: local evaluation in a server SDK, a bootstrap, or the customer's own assignment.
    EVALUATED_OUTSIDE_FLAG_SERVICE = "evaluated_outside_flag_service"


@frozen
class _Pins:
    pinned: tuple[ReachableCondition, ...]
    all_pinned: bool
    # The pinned conditions whose variant the analysis includes, in evaluation order.
    analyzed: tuple[ReachableCondition, ...]
    weighted: tuple[ReachableCondition, ...]
    split: Split
    # The analyzed pins to a variant with 0% in the split. The split sends nobody there, so they don't bias the
    # other variants, but that variant's results show only the pinned users.
    unweighted: tuple[ReachableCondition, ...]


@frozen
class PinnedShareMeasurement:
    most_pinned_variant: str
    pinned_people: int
    # The variant's pinned people, and its weight in the split of the people assigned at random.
    variant_people: float
    # The people that a condition set served, without those pinned to a variant with 0% in the split.
    matched_people: int
    remotely_evaluated_share: float | None
    since: datetime
    team_timezone: str

    @property
    def share(self) -> float:
        return self.pinned_people / self.variant_people if self.variant_people else 0.0


@frozen
class PinnedShareGrade:
    """The share that sets the severity of SOME_CONDITIONS_PINNED, or the reason it is unknown."""

    measurement: PinnedShareMeasurement | None
    share: float | None
    unknown_reason: PinnedShareUnknownReason | None

    def evidence(self) -> dict[str, str | int | float | None]:
        evidence: dict[str, str | int | float | None] = {}
        if self.measurement is not None:
            remotely_evaluated_share = self.measurement.remotely_evaluated_share
            evidence["most_pinned_variant"] = self.measurement.most_pinned_variant
            evidence["pinned_people"] = self.measurement.pinned_people
            evidence["variant_people"] = round(self.measurement.variant_people)
            evidence["matched_people"] = self.measurement.matched_people
            evidence["remotely_evaluated_share"] = (
                None if remotely_evaluated_share is None else round(remotely_evaluated_share, 4)
            )
        if self.share is not None:
            evidence["pinned_share"] = round(self.share, 4)
        if self.unknown_reason is not None:
            evidence["reason"] = self.unknown_reason.value
        return evidence

    def sentence(self, them: str) -> str:
        """The measured share in words, or why it can't be measured, after a leading space. Empty otherwise."""
        measurement = self.measurement
        if self.share is not None and measurement is not None:
            return (
                f" Since {format_change_time(measurement.since, measurement.team_timezone)}, about "
                f'{percent(self.share)} of the users who got "{measurement.most_pinned_variant}" matched {them} '
                f"({measurement.pinned_people:,} of about {round(measurement.variant_people):,})."
            )
        if self.unknown_reason == PinnedShareUnknownReason.EVALUATED_OUTSIDE_FLAG_SERVICE:
            return (
                " Most of this flag's calls are evaluated locally in a server SDK, bootstrapped, or assigned in your "
                f"own code, so PostHog can't measure how many users match {them}."
            )
        return ""


def needs_condition_set_traffic(ctx: HealthContext) -> bool:
    """Whether a check grades its finding by the users that pinned conditions served: this check for
    SOME_CONDITIONS_PINNED, and the release-condition check for an override removed after launch."""
    return ctx.is_launched and any(pins.weighted for pins in _graded_pins(ctx))


def has_too_few_people(ctx: HealthContext, traffic: ConditionSetTraffic) -> bool:
    """Whether a check leaves the share of `traffic` unknown only because too few people count."""
    return any(
        pins.weighted and _grade(pins, traffic).unknown_reason == PinnedShareUnknownReason.TOO_FEW_PEOPLE
        for pins in _graded_pins(ctx)
    )


def removed_override_grade(ctx: HealthContext) -> PinnedShareGrade | None:
    """The share of a variant's users that the overrides removed after launch would serve if they were still in
    place, which the release-condition check grades them by. None when no removed override has a weight to grade."""
    pins = _removed_pins(ctx)
    if pins is None or not pins.weighted:
        return None
    return _grade(pins, ctx.condition_set_traffic)


def pinned_share_severity(grade: PinnedShareGrade | None) -> ExperimentHealthFindingSeverity | None:
    """The severity of a finding graded by a pinned share. None when the share is too small for a finding."""
    if grade is None or grade.share is None:
        return ExperimentHealthFindingSeverity.INFO
    if grade.share < _NO_FINDING_BELOW_SHARE:
        return None
    return (
        ExperimentHealthFindingSeverity.WARNING
        if grade.share > _WARNING_ABOVE_SHARE
        else ExperimentHealthFindingSeverity.INFO
    )


def forced_variant_release_condition(ctx: HealthContext) -> ExperimentHealthFinding | None:
    flag = ctx.flag
    pins = _pins(ctx)
    if flag is None or pins is None:
        return None
    is_draft = not ctx.is_launched

    if not pins.all_pinned:
        return _some_conditions_pinned(pins, ctx, is_draft)

    pinned_numbers = [condition.number for condition in pins.pinned]
    pinned_keys = _variant_keys(pins.pinned)
    # The shipped finding already says that everyone gets this variant.
    if ctx.is_running and is_single_variant_shipped(flag) and pinned_keys == [shipped_variant_key(flag)]:
        return None
    set_after_launch = _set_after_launch(ctx, pinned_numbers)
    return _finding(
        subcode=ALL_CONDITIONS_PINNED,
        severity=ExperimentHealthFindingSeverity.WARNING,
        title="No users are randomly assigned to a variant",
        detail=_all_pinned_detail(pinned_numbers, pinned_keys, is_draft, set_after_launch.sentence),
        pinned_numbers=pinned_numbers,
        pinned_keys=pinned_keys,
        diagnostic_ref="A7b",
        grade_evidence=set_after_launch.evidence,
    )


def _pins(ctx: HealthContext) -> _Pins | None:
    flag = ctx.flag
    # After the end the flag often holds the shipped decision, not the setup of the run.
    if flag is None or flag.deleted or ctx.has_ended or ctx.archived:
        return None
    pinned = tuple(condition for condition in flag.reachable_conditions if condition.pinned_variant is not None)
    if not pinned:
        return None
    # A variant that the experiment excludes is not in the results, so its pins can't bias them.
    analyzed = tuple(condition for condition in pinned if condition.pinned_variant not in ctx.excluded_variant_keys)
    unweighted_keys = {variant.key for variant in flag.variants if variant.rollout_percentage == 0}
    return _Pins(
        pinned=pinned,
        all_pinned=len(pinned) == len(flag.reachable_conditions),
        analyzed=analyzed,
        weighted=tuple(condition for condition in analyzed if condition.pinned_variant not in unweighted_keys),
        split=flag.variants,
        unweighted=tuple(condition for condition in analyzed if condition.pinned_variant in unweighted_keys),
    )


def _removed_pins(ctx: HealthContext) -> _Pins | None:
    """The overrides removed after launch, as pins on the conditions that held them."""
    history = ctx.flag_history
    flag = ctx.flag
    if not isinstance(history, FlagHistory) or flag is None or flag.deleted or not ctx.is_running or ctx.archived:
        return None
    effect = conditions_net_effect(history.counted(ConditionsChange))
    if effect is None:
        return None
    pinned = tuple(
        ReachableCondition(number=override.condition_number, pinned_variant=override.variant)
        for override in effect.overrides.removed
        if override.condition_number is not None and override.variant not in ctx.excluded_variant_keys
    )
    if not pinned:
        return None
    unweighted_keys = {variant.key for variant in flag.variants if variant.rollout_percentage == 0}
    return _Pins(
        pinned=pinned,
        all_pinned=False,
        analyzed=pinned,
        weighted=tuple(condition for condition in pinned if condition.pinned_variant not in unweighted_keys),
        split=flag.variants,
        unweighted=tuple(condition for condition in pinned if condition.pinned_variant in unweighted_keys),
    )


def _graded_pins(ctx: HealthContext) -> list[_Pins]:
    pins = _pins(ctx)
    removed = _removed_pins(ctx)
    return [
        *([pins] if pins is not None and not pins.all_pinned else []),
        *([removed] if removed is not None else []),
    ]


def _some_conditions_pinned(pins: _Pins, ctx: HealthContext, is_draft: bool) -> ExperimentHealthFinding | None:
    if not pins.analyzed:
        return None
    grade = None if is_draft or not pins.weighted else _grade(pins, ctx.condition_set_traffic)
    share = grade.share if grade is not None else None
    if share is not None and share < _NO_FINDING_BELOW_SHARE and not pins.unweighted:
        return None
    pinned_numbers = [condition.number for condition in pins.analyzed]
    pinned_keys = _variant_keys(pins.analyzed)
    set_after_launch = _set_after_launch(ctx, pinned_numbers)
    return _finding(
        subcode=SOME_CONDITIONS_PINNED,
        severity=ExperimentHealthFindingSeverity.WARNING
        if share is not None and share > _WARNING_ABOVE_SHARE
        else ExperimentHealthFindingSeverity.INFO,
        title="Some users are not randomly assigned to a variant",
        detail=_some_pinned_detail(
            pinned_numbers, pinned_keys, is_draft, grade, _variant_keys(pins.unweighted), set_after_launch.sentence
        ),
        pinned_numbers=pinned_numbers,
        pinned_keys=pinned_keys,
        diagnostic_ref="A7",
        grade_evidence={**(grade.evidence() if grade is not None else {}), **set_after_launch.evidence},
    )


@frozen
class _SetAfterLaunch:
    # One sentence after a leading space, or empty when no override was set after launch.
    sentence: str
    evidence: dict[str, str | int | float | None]


def _set_after_launch(ctx: HealthContext, numbers: Sequence[int]) -> _SetAfterLaunch:
    """The overrides of these conditions that were set after launch while people were already exposed. The
    release-condition check leaves them to this finding, so that one override gets one row."""
    history = ctx.flag_history
    effect = conditions_net_effect(history.counted(ConditionsChange)) if isinstance(history, FlagHistory) else None
    added = [] if effect is None else [o for o in effect.overrides.added if o.condition_number in numbers]
    if history is None or not added:
        return _SetAfterLaunch(sentence="", evidence={})
    set_at = max(override.set_at for override in added)
    at = format_change_time(set_at, history.team_timezone)
    if len(added) == 1:
        sentence = (
            f" The override of Set {added[0].condition_number} was set on {at}, after launch, so users it matches "
            "who were exposed before may have switched variants."
        )
    else:
        names = _set_names(sorted(override.condition_number for override in added))
        sentence = (
            f" The overrides of {names} were set after launch, last on {at}, so users they match who were exposed "
            "before may have switched variants."
        )
    return _SetAfterLaunch(sentence=sentence, evidence={"override_set_at": set_at.astimezone(UTC).isoformat()})


def _grade(pins: _Pins, traffic: ConditionSetTraffic | None) -> PinnedShareGrade:
    if traffic is None:
        return PinnedShareGrade(measurement=None, share=None, unknown_reason=PinnedShareUnknownReason.NOT_MEASURED)
    measurement = _measure(pins, traffic)
    remotely_evaluated_share = measurement.remotely_evaluated_share
    unknown_reason = (
        PinnedShareUnknownReason.EVALUATED_OUTSIDE_FLAG_SERVICE
        if remotely_evaluated_share is not None and remotely_evaluated_share < _MIN_REMOTELY_EVALUATED_SHARE_TO_CLEAR
        else PinnedShareUnknownReason.TOO_FEW_PEOPLE
    )
    if measurement.matched_people < _MIN_MATCHED_PEOPLE:
        return PinnedShareGrade(measurement=measurement, share=None, unknown_reason=unknown_reason)
    share = measurement.share
    clearing_needs_more_calls = (
        remotely_evaluated_share is None or remotely_evaluated_share < _MIN_REMOTELY_EVALUATED_SHARE_TO_CLEAR
    )
    if share < _NO_FINDING_BELOW_SHARE and clearing_needs_more_calls:
        return PinnedShareGrade(measurement=measurement, share=None, unknown_reason=unknown_reason)
    return PinnedShareGrade(measurement=measurement, share=share, unknown_reason=None)


def _measure(pins: _Pins, traffic: ConditionSetTraffic) -> PinnedShareMeasurement:
    excluded_numbers = {condition.number for condition in pins.unweighted}
    matched_people = sum(people for number, people in traffic.people_by_set.items() if number not in excluded_numbers)
    pinned_by_variant = dict.fromkeys(_variant_keys(pins.weighted), 0)
    for condition in pins.weighted:
        if condition.pinned_variant is not None:
            pinned_by_variant[condition.pinned_variant] += traffic.people_by_set.get(condition.number, 0)
    randomized_people = matched_people - sum(pinned_by_variant.values())
    weights = {variant.key: variant.rollout_percentage for variant in pins.split}

    def variant_people(key: str) -> float:
        weight = weights.get(key)
        # An unreadable weight counts as the whole split, which gives the lowest share the pins can have.
        return pinned_by_variant[key] + randomized_people * (1.0 if weight is None else weight / 100)

    def share(key: str) -> float:
        people = variant_people(key)
        return pinned_by_variant[key] / people if people else 0.0

    most_pinned_variant = max(pinned_by_variant, key=share)
    return PinnedShareMeasurement(
        most_pinned_variant=most_pinned_variant,
        pinned_people=pinned_by_variant[most_pinned_variant],
        variant_people=variant_people(most_pinned_variant),
        matched_people=matched_people,
        remotely_evaluated_share=traffic.remotely_evaluated_calls / traffic.calls if traffic.calls else None,
        since=traffic.since,
        team_timezone=traffic.team_timezone,
    )


def _variant_keys(conditions: Sequence[ReachableCondition]) -> list[str]:
    return list(dict.fromkeys(condition.pinned_variant for condition in conditions if condition.pinned_variant))


def _quoted(keys: Sequence[str]) -> str:
    return ", ".join(f'"{key}"' for key in keys)


def _set_names(numbers: Sequence[int]) -> str:
    if len(numbers) == 1:
        return f"Set {numbers[0]}"
    return "Sets " + ", ".join(str(number) for number in numbers[:-1]) + f" and {numbers[-1]}"


def _all_pinned_detail(
    numbers: Sequence[int], pinned_keys: Sequence[str], is_draft: bool, set_after_launch: str
) -> str:
    overrides = "the override" if len(numbers) == 1 else "the overrides"
    when = "after launch " if is_draft else ""
    if len(pinned_keys) == 1:
        key = pinned_keys[0]
        fact = (
            f'Every release condition that includes users sets the variant override "{key}", so {when}all users '
            f'in the experiment get "{key}".'
        )
        why = f'With no other variant to compare against, the results can\'t show whether "{key}" makes a difference.'
        fix = (
            f'If you meant to roll out "{key}", end the experiment with a conclusion. Otherwise remove {overrides} '
            f'so users are assigned at random. Users who already saw "{key}" can then switch to another variant.'
        )
    else:
        fact = (
            f"Every release condition that includes users sets a variant override ({_quoted(pinned_keys)}), so "
            f"{when}each user gets the variant of the condition they match instead of a random one."
        )
        why = (
            "Each variant then holds a different group of users, so a difference in the results can come from "
            "who those users are and not from the variant."
        )
        fix = (
            f"Remove {overrides} so users are assigned at random. Users who already saw a variant can then "
            "switch to another one."
        )
    if is_draft:
        fix = f"Remove {overrides} before launch so users are assigned at random."
    return f"{fact}{set_after_launch} {why} {fix}"


def _some_pinned_detail(
    numbers: Sequence[int],
    pinned_keys: Sequence[str],
    is_draft: bool,
    grade: PinnedShareGrade | None,
    unweighted_keys: Sequence[str],
    set_after_launch: str,
) -> str:
    if len(numbers) == 1:
        key = pinned_keys[0]
        overrides, them = "the override", "it"
        fact = (
            f'{_set_names(numbers)} sets the variant override "{key}", so users who match it always get "{key}" '
            "instead of a random variant."
        )
    else:
        overrides, them = "the overrides", "them"
        fact = (
            f"{_set_names(numbers)} set variant overrides ({_quoted(pinned_keys)}), so users who match them "
            "always get the variant of their condition instead of a random one."
        )
    why = (
        f"{'After launch they count' if is_draft else 'They still count'} in the results, so if they behave "
        "differently from other users, the results of their variant shift for a reason other than the variant."
    )
    if is_draft:
        fix = (
            f"An override helps to test the experiment before launch. Remove {them} before launch, unless the "
            "filter for internal and test users excludes these users from the results."
        )
    else:
        fix = (
            "If these are internal or test users, check that the filter for internal and test users excludes "
            f"them from the results. Otherwise remove {overrides}."
        )
    if grade is not None:
        fact += grade.sentence(them)
    if len(unweighted_keys) == 1:
        fact += (
            f' Nobody gets "{unweighted_keys[0]}" at random, so the results of "{unweighted_keys[0]}" show only '
            "these users."
        )
    elif unweighted_keys:
        names = " or ".join(f'"{key}"' for key in unweighted_keys)
        fact += f" Nobody gets {names} at random, so their results show only these users."
    return f"{fact}{set_after_launch} {why} {fix}"


def percent(share: float) -> str:
    return f"{share * 100:.1f}".removesuffix(".0") + "%"


def _finding(
    *,
    subcode: str,
    severity: ExperimentHealthFindingSeverity,
    title: str,
    detail: str,
    pinned_numbers: Sequence[int],
    pinned_keys: Sequence[str],
    diagnostic_ref: str,
    grade_evidence: Mapping[str, str | int | float | None] | None = None,
) -> ExperimentHealthFinding:
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.FORCED_VARIANT_RELEASE_CONDITION,
        subcode=subcode,
        severity=severity,
        title=title,
        detail=detail,
        evidence={
            "pinned_condition_sets": ", ".join(str(number) for number in pinned_numbers),
            "pinned_variant_keys": ", ".join(pinned_keys),
            **(grade_evidence or {}),
        },
        actions=(ExperimentHealthFindingActionKind.EDIT_RELEASE_CONDITIONS,),
        diagnostic_ref=diagnostic_ref,
    )
