from collections.abc import Mapping
from zoneinfo import ZoneInfo

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthValueKey,
)
from products.experiments.backend.health.checks.bias_risk import MULTIPLE_VARIANT_KEY
from products.experiments.backend.health.checks.forced_variant import assigns_nobody_by_split
from products.experiments.backend.health.context import ExposureTotals, FlagState, HealthContext
from products.experiments.backend.health.pinned_share import pinned_variant_keys
from products.experiments.backend.health.skips import (
    RUNS_AFTER_LAUNCH,
    CheckOutcome,
    CheckSkip,
    CheckValues,
    flag_to_check,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.split_changes import format_change_time

# pinned: the finding's subcodes. The page sends them as `finding_subcode` on the health finding events.
FLAG_OFF = "flag_off"
VARIANT_NOT_SERVED = "variant_not_served"

# Each of these users is a fact, as in `multiple_variants_share`, so the floor only stops a few testers.
UNSERVED_MINIMUM_COUNT = 5
# On the 0-100 scale. Below it, the users that the flag doesn't serve are too few of the new users to move the results.
UNSERVED_SHARE_THRESHOLD = 1.0
# A default value lands in one variant. A bootstrap, cached flags or an outside assignment spread over all of them.
ONE_VARIANT_SHARE = 0.9


@frozen
class _Unserved:
    """The users first exposed after the day of the flag's last save, which is the first day that only the current setup
    can have served."""

    first_exposed: int
    by_variant: Mapping[str, int]

    @property
    def count(self) -> int:
        return sum(self.by_variant.values())

    @property
    def percentage(self) -> float:
        return self.count / self.first_exposed * 100 if self.first_exposed else 0.0


def served_variants(flag: FlagState) -> frozenset[str]:
    """The variants that the flag's setup can give a user: the overrides of the release conditions that can serve a
    request, and the variants with a share of the split when one of those conditions uses the split. Empty when the
    flag is off."""
    if not flag.active:
        return frozenset()
    overrides = frozenset(pinned_variant_keys(flag.reachable_conditions))
    if assigns_nobody_by_split(flag):
        return overrides
    # A variant without a rollout percentage counts as active, as on the flag itself.
    split = {
        variant.key
        for variant in flag.variants
        if variant.key and (variant.rollout_percentage is None or variant.rollout_percentage > 0)
    }
    return overrides | split


def unserved_variant_values(ctx: HealthContext) -> CheckValues:
    judged = _judged(ctx)
    if isinstance(judged, CheckSkip):
        return {}
    unserved = _unserved(ctx, *judged)
    return {
        ExperimentHealthValueKey.UNSERVED_EXPOSED_COUNT: unserved.count,
        ExperimentHealthValueKey.UNSERVED_EXPOSED_PERCENTAGE: round(unserved.percentage, 2),
    }


def unserved_variant_exposures(ctx: HealthContext) -> CheckOutcome:
    judged = _judged(ctx)
    if isinstance(judged, CheckSkip):
        return judged
    flag, exposures = judged
    unserved = _unserved(ctx, flag, exposures)
    if unserved.count < UNSERVED_MINIMUM_COUNT or unserved.percentage <= UNSERVED_SHARE_THRESHOLD:
        return None
    return _finding(ctx, flag, exposures, unserved)


def _judged(ctx: HealthContext) -> tuple[FlagState, ExposureTotals] | CheckSkip:
    """The flag and the exposures that the check judges, or why it doesn't."""
    exposures = ctx.exposures
    if exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    flag = flag_to_check(ctx, before_launch=False)
    if isinstance(flag, CheckSkip):
        return flag
    events = ctx.exposure_events
    if events is not None and events.activation is not None:
        return not_applicable("The exposure criteria count users at an activation, not at the flag call")
    # Then every variant comes from an assignment outside the flag. On a 0% rollout the flag-state check reports it
    # from the flag's calls.
    if flag.active and not flag.reachable_conditions:
        return not_applicable("Doesn't run on a flag that serves nobody, such as one with a 0% rollout")
    if flag.saved_at is None:
        return not_checked("Couldn't check because the time of the flag's last save is unknown")
    return flag, exposures


def _unserved(ctx: HealthContext, flag: FlagState, exposures: ExposureTotals) -> _Unserved:
    assert flag.saved_at is not None
    # A user exposed on the day of the save can have got the variant from the setup before it. Clients that cached the
    # flags, and server SDKs that poll the flag definitions, also keep the old setup for a while after the save.
    saved_on = flag.saved_at.astimezone(ZoneInfo(ctx.team_timezone)).date()
    after = {
        variant: sum(count for day, count in daily.items() if day > saved_on)
        for variant, daily in exposures.daily_exposures.items()
    }
    served = served_variants(flag)
    return _Unserved(
        first_exposed=sum(after.values()),
        by_variant={
            variant: count
            for variant, count in after.items()
            if count and variant != MULTIPLE_VARIANT_KEY and variant not in served
        },
    )


def _finding(
    ctx: HealthContext, flag: FlagState, exposures: ExposureTotals, unserved: _Unserved
) -> ExperimentHealthFinding:
    assert flag.saved_at is not None
    unit = exposures.unit
    saved = format_change_time(flag.saved_at, ctx.team_timezone)
    count = unserved.count
    users = f"{count:,} {unit}{'' if count == 1 else 's'}"
    ranked = sorted(unserved.by_variant.items(), key=lambda item: (-item[1], item[0]))
    top_variant, top_count = ranked[0]
    one_variant = top_count >= ONE_VARIANT_SHARE * count
    if flag.active:
        subcode = VARIANT_NOT_SERVED
        setup = _why_not_served(flag, [variant for variant, _ in ranked], saved, unit)
        exposed = f"But {users} were first exposed in {'it' if len(ranked) == 1 else 'them'} after that day."
        variants = "a variant" if len(ranked) == 1 else "variants"
        title = f"{unit.capitalize()}s are exposed in {variants} that the feature flag doesn't serve"
        default_value = (
            "Your code can send a default value as the variant when the flag returns none, and clients can still hold "
            "flags from before the save."
        )
    else:
        subcode = FLAG_OFF
        title = f"{unit.capitalize()}s are exposed while the feature flag is off"
        setup = f"The feature flag is off and was last saved on {saved}, so it gives no {unit} a variant."
        exposed = (
            f'But {users} were first exposed after that day, {top_count:,} of them in "{top_variant}".'
            if one_variant
            else f"But {users} were first exposed after that day."
        )
        default_value = (
            "Exposures that land in one variant usually come from your code, which sends a default value as the "
            "variant when the flag returns none."
        )
    if one_variant:
        severity = ExperimentHealthFindingSeverity.WARNING
        cause = [
            f"They count in the results, so the variants compare {unit}s that the flag didn't assign.",
            default_value,
            f"Send the exposure only with the variant that the flag returns, and record no exposure for a {unit} that "
            "gets none.",
        ]
    else:
        severity = ExperimentHealthFindingSeverity.INFO
        cause = [
            "They count in the results. Their variants come from outside the flag, for example from a bootstrap, from "
            "flags that a client cached before the save, or from your own assignment, so the flag's setup doesn't "
            "decide who gets which variant.",
            "If PostHog should assign the variants, stop setting them in your code.",
        ]
    return ExperimentHealthFinding(
        code=ExperimentHealthFindingCode.UNSERVED_VARIANT_EXPOSURES,
        subcode=subcode,
        severity=severity,
        title=title,
        detail=" ".join([setup, exposed, *cause]),
        evidence={
            "saved_at": flag.saved_at.isoformat(),
            "first_exposed_after_save": unserved.first_exposed,
            "unserved_exposed_count": count,
            "unserved_exposed_percentage": round(unserved.percentage, 2),
            "unserved_variants": ",".join(variant for variant, _ in ranked),
        },
        actions=(),
        diagnostic_ref="A9",
    )


def _why_not_served(flag: FlagState, keys: list[str], saved: str, unit: str) -> str:
    """The sentence that says why the flag's setup gives nobody these variants."""
    one = len(keys) == 1
    quoted = ", ".join(f'"{key}"' for key in keys)
    variants = f"the variant {quoted}" if one else f"the variants {quoted}"
    if assigns_nobody_by_split(flag):
        overrides = ", ".join(f'"{key}"' for key in pinned_variant_keys(flag.reachable_conditions))
        why = (
            f"every release condition that can serve a {unit} sets a variant override ({overrides}), so it gives no "
            f"{unit} {variants}."
        )
    else:
        why = f"it gives no {unit} {variants}: " + (
            "the variant has no share of the split, and no release condition sets it."
            if one
            else "they have no share of the split, and no release condition sets them."
        )
    return f"Since the feature flag was last saved on {saved}, {why}"
