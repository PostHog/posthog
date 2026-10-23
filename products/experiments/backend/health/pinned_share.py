"""
The share of a variant's users that release conditions with a variant override serve, which grades the findings
about overrides: the forced-variant check grades the overrides in place, and the release-condition check the ones
removed after launch. Pure functions, no I/O: `health/condition_set_traffic.py` loads the traffic.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import ExperimentHealthFindingSeverity
from products.experiments.backend.health.context import ConditionSetTraffic, ReachableCondition
from products.experiments.backend.health.split_changes import format_change_time
from products.feature_flags.backend.facade.edits import Split

# A finding is graded by the largest share that pinned users make up of one variant's users, in this window, or
# since launch or the flag's last save if later. The bias is per variant, so a few pinned users weigh more in a
# small variant. Below the first share they can't move a variant's results much, so there is no finding. Above the
# second they are a warning.
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
class PinnedConditions:
    """The release conditions with a variant override that a finding is graded by."""

    # The conditions pinned to a variant with a weight in the split, in evaluation order.
    weighted: tuple[ReachableCondition, ...]
    # The conditions pinned to a variant with 0% in the split. The split sends nobody there, so they don't bias the
    # other variants, but that variant's results show only the pinned users.
    unweighted: tuple[ReachableCondition, ...]
    split: Split
    # False when some pinned users have no condition left that counts them, so a small share can't clear them.
    all_counted: bool


def pinned_conditions(
    conditions: Sequence[ReachableCondition], split: Split, *, all_counted: bool = True
) -> PinnedConditions:
    unweighted_keys = {variant.key for variant in split if variant.rollout_percentage == 0}
    return PinnedConditions(
        weighted=tuple(condition for condition in conditions if condition.pinned_variant not in unweighted_keys),
        unweighted=tuple(condition for condition in conditions if condition.pinned_variant in unweighted_keys),
        split=split,
        all_counted=all_counted,
    )


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
    """The share that sets the severity of a finding about pinned conditions, or the reason it is unknown."""

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


def grade_pinned_share(pins: PinnedConditions, traffic: ConditionSetTraffic | None) -> PinnedShareGrade:
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
    if share < _NO_FINDING_BELOW_SHARE and not pins.all_counted:
        return PinnedShareGrade(
            measurement=measurement, share=None, unknown_reason=PinnedShareUnknownReason.NOT_MEASURED
        )
    return PinnedShareGrade(measurement=measurement, share=share, unknown_reason=None)


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


def pinned_variant_keys(conditions: Sequence[ReachableCondition]) -> list[str]:
    return list(dict.fromkeys(condition.pinned_variant for condition in conditions if condition.pinned_variant))


def percent(share: float) -> str:
    return f"{share * 100:.1f}".removesuffix(".0") + "%"


def _measure(pins: PinnedConditions, traffic: ConditionSetTraffic) -> PinnedShareMeasurement:
    excluded_numbers = {condition.number for condition in pins.unweighted}
    matched_people = sum(people for number, people in traffic.people_by_set.items() if number not in excluded_numbers)
    pinned_by_variant = dict.fromkeys(pinned_variant_keys(pins.weighted), 0)
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
