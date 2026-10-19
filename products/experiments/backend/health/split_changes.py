"""
Changes of a flag's variant split, read from the flag's activity log. Pure functions, no I/O.

The flag service draws a variant from a hash, and each variant is a slot of the split in stored order
(`select_variant` in `rust/feature-flags/src/flags/v1_bucketing.rs`). A changed split moves the slot boundaries,
so people whose hash lies between an old and a new boundary get another variant. A rollout change, or a
release-condition change without a variant override, moves people into or out of the flag, never to another
variant, so only the split counts here.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from posthog.dataclasses import frozen

from products.experiments.backend.health.context import Split, SplitChange, parse_variants


class SplitChangeShape(StrEnum):
    # pinned: the finding's subcodes. The page sends them as `finding_variant` on the health finding events.
    VARIANT_ROLLED_OUT = "variant_rolled_out"
    VARIANT_REMOVED = "variant_removed"
    VARIANT_ADDED = "variant_added"
    VARIANT_ZEROED = "variant_zeroed"
    REORDERED = "reordered"
    REBALANCED = "rebalanced"
    REVERTED = "reverted"


@frozen
class SplitNetEffect:
    shape: SplitChangeShape
    from_split: Split
    to_split: Split
    first: SplitChange
    last: SplitChange
    change_count: int


# Freezing narrows the release conditions to the exposed people, and unfreezing undoes it. Both write the whole
# `filters` value, but neither moves an exposed person to another variant, and the experiment's frozen status
# already reports them.
EXPOSURE_FREEZE_JOB_TYPES = frozenset({"experiment_exposure_frozen", "experiment_exposure_unfrozen"})


def split_change_from_activity(
    *, changed_at: datetime, job_type: object, before_variants: object, after_variants: object
) -> SplitChange | None:
    """The split change in one activity log row of the flag, or None when the row does not change the split."""
    if job_type in EXPOSURE_FREEZE_JOB_TYPES:
        return None
    before = parse_variants(before_variants)
    after = parse_variants(after_variants)
    if same_assignment(before, after):
        return None
    return SplitChange(changed_at=changed_at, before=before, after=after)


def split_shape(before: Split, after: Split) -> SplitChangeShape:
    """The shape of a change from one split to another, for two splits that differ. The first match wins."""
    rolled_out = rolled_out_variant_key(after)
    # Also a switch of the variant at 100%, so the shipped finding covers it without a second row.
    if rolled_out is not None and rolled_out != rolled_out_variant_key(before):
        return SplitChangeShape.VARIANT_ROLLED_OUT
    # A rename counts as a removal, because the analysis drops the exposures of a key the flag no longer has.
    if removed_variant_keys(before, after):
        return SplitChangeShape.VARIANT_REMOVED
    if added_variant_keys(before, after):
        return SplitChangeShape.VARIANT_ADDED
    if zeroed_variant_keys(before, after):
        return SplitChangeShape.VARIANT_ZEROED
    if Counter(served_slots(before)) == Counter(served_slots(after)):
        return SplitChangeShape.REORDERED
    return SplitChangeShape.REBALANCED


def net_effect(changes: Sequence[SplitChange]) -> SplitNetEffect | None:
    if not changes:
        return None
    first = changes[0]
    last = changes[-1]
    return SplitNetEffect(
        shape=(
            SplitChangeShape.REVERTED
            if same_assignment(first.before, last.after)
            else split_shape(first.before, last.after)
        ),
        from_split=first.before,
        to_split=last.after,
        first=first,
        last=last,
        change_count=len(changes),
    )


def served_slots(split: Split) -> Split:
    # The flag service walks the cumulative percentages in order, so a variant at 0% has no range and serves
    # nobody. A percentage it can't read counts as served.
    return tuple(variant for variant in split if variant.rollout_percentage != 0)


def same_assignment(before: Split, after: Split) -> bool:
    """Whether both splits give every person the same variant."""
    return served_slots(before) == served_slots(after)


def rolled_out_variant_key(split: Split) -> str | None:
    # A holdout is drawn before the split with a hash of its own, so one variant at 100% is a rollout also
    # when the flag has a holdout.
    full = [variant for variant in split if variant.rollout_percentage == 100]
    return full[0].key if len(full) == 1 else None


def removed_variant_keys(before: Split, after: Split) -> list[str]:
    return _keys_missing_from(after, split=served_slots(before))


def added_variant_keys(before: Split, after: Split) -> list[str]:
    return _keys_missing_from(before, split=served_slots(after))


def zeroed_variant_keys(before: Split, after: Split) -> list[str]:
    served_before = {variant.key for variant in served_slots(before)}
    return [
        variant.key
        for variant in after
        if variant.key and variant.rollout_percentage == 0 and variant.key in served_before
    ]


def split_variant_keys(split: Split) -> tuple[str, ...]:
    return tuple(variant.key for variant in split if variant.key)


def describe_split(split: Split) -> str:
    """The split as the evidence and the wording show it, for example "control 50% / test 50%"."""
    if not split:
        return "no variants"
    return " / ".join(
        f"{variant.key or 'unnamed'} {variant.rollout_percentage:g}%"
        if variant.rollout_percentage is not None
        else variant.key or "unnamed"
        for variant in split
    )


def format_change_time(value: datetime, team_timezone: str) -> str:
    # The format of the alert messages (posthog/tasks/alerts/utils.py). The time matters, because a start
    # date moved to the change must not keep the hours before it.
    return value.astimezone(ZoneInfo(team_timezone)).strftime("%B %-d, %Y at %-I:%M %p %Z")


def _keys_missing_from(other: Split, *, split: Split) -> list[str]:
    other_keys = {variant.key for variant in other}
    return [variant.key for variant in split if variant.key and variant.key not in other_keys]
