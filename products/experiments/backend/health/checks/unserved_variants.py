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
from products.experiments.backend.health.context import ExposureTotals, FlagState, HealthContext
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

# Each of these users is a fact, as in `multiple_variants_share`. The floor stops one or two testers who force a
# variant from firing the finding.
UNSERVED_MINIMUM_COUNT = 5
# On the 0-100 scale. Below it, the users that the flag doesn't serve are too few of the new users to move the results.
UNSERVED_SHARE_THRESHOLD = 1.0
# The share of the unserved users in one variant from which the finding is a warning that names that variant as the
# value that your code sends. A default value lands in one variant, while a bootstrap, cached flags or the customer's own
# assignment spread over all of them.
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
    overrides = {condition.pinned_variant for condition in flag.reachable_conditions if condition.pinned_variant}
    if all(condition.pinned_variant is not None for condition in flag.reachable_conditions):
        return frozenset(overrides)
    # A variant without a rollout percentage counts as active, as on the flag itself.
    split = {
        variant.key
        for variant in flag.variants
        if variant.key and (variant.rollout_percentage is None or variant.rollout_percentage > 0)
    }
    return frozenset(overrides | split)


def unserved_variant_values(ctx: HealthContext) -> CheckValues:
    flag = ctx.flag
    if ctx.exposures is None or flag is None or flag.saved_at is None:
        return {}
    unserved = _unserved(ctx, flag, ctx.exposures)
    return {
        ExperimentHealthValueKey.UNSERVED_EXPOSED_COUNT: unserved.count,
        ExperimentHealthValueKey.UNSERVED_EXPOSED_PERCENTAGE: round(unserved.percentage, 2),
    }


def unserved_variant_exposures(ctx: HealthContext) -> CheckOutcome:
    exposures = ctx.exposures
    if exposures is None:
        return not_applicable(RUNS_AFTER_LAUNCH)
    flag = flag_to_check(ctx, before_launch=False)
    if isinstance(flag, CheckSkip):
        return flag
    events = ctx.exposure_events
    # With an activation, the exposure query dates a user by the activation, which can come long after the flag call
    # that set the variant.
    if events is not None and events.activation is not None:
        return not_applicable("The exposure criteria count users at an activation, not at the flag call")
    # With every release condition at 0%, the variants come from the customer's own assignment, which the flag-state
    # check reports from the flag's calls.
    if flag.active and not flag.reachable_conditions:
        return not_applicable("The flag-state check reports a flag with a 0% rollout")
    if flag.saved_at is None:
        return not_checked("Couldn't check because the time of the flag's last save is unknown")
    unserved = _unserved(ctx, flag, exposures)
    if unserved.count < UNSERVED_MINIMUM_COUNT or unserved.percentage <= UNSERVED_SHARE_THRESHOLD:
        return None
    return _finding(ctx, flag, exposures, unserved)


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
        keys = [variant for variant, _ in ranked]
        quoted = ", ".join(f'"{key}"' for key in keys)
        subcode = VARIANT_NOT_SERVED
        title = (
            f"{unit.capitalize()}s are exposed in a variant that the feature flag doesn't serve"
            if len(keys) == 1
            else f"{unit.capitalize()}s are exposed in variants that the feature flag doesn't serve"
        )
        setup = (
            f"Since the feature flag was last saved on {saved}, it gives no {unit} the variant {quoted}: the variant "
            "has no share of the split, and no release condition sets it."
            if len(keys) == 1
            else f"Since the feature flag was last saved on {saved}, it gives no {unit} the variants {quoted}: they "
            "have no share of the split, and no release condition sets them."
        )
        exposed = f"But {users} were first exposed in {'it' if len(keys) == 1 else 'them'} after that day."
    else:
        subcode = FLAG_OFF
        title = f"{unit.capitalize()}s are exposed while the feature flag is off"
        setup = f"The feature flag is off and was last saved on {saved}, so it gives no {unit} a variant."
        exposed = (
            f'But {users} were first exposed after that day, {top_count:,} of them in "{top_variant}".'
            if one_variant
            else f"But {users} were first exposed after that day."
        )
    if one_variant:
        severity = ExperimentHealthFindingSeverity.WARNING
        cause = [
            f"They count in the results, so the variants compare {unit}s that the flag didn't assign.",
            f'Most of them are in "{top_variant}", which usually means that your code sends it as a default value when '
            "the flag returns no variant.",
            f"Send the exposure only with the variant that the flag returns, and record no exposure for a {unit} that "
            "gets none.",
        ]
    else:
        # Spread over the variants, the values come from an assignment that splits the users, as on a flag with a 0%
        # rollout, so they bias the results only as much as that assignment does.
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
            **{f"unserved_exposed_{variant}": exposed_count for variant, exposed_count in ranked},
        },
        actions=(),
        diagnostic_ref="A9",
    )
