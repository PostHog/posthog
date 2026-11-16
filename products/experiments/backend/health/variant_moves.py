"""
The flag changes after launch that can give users who were already exposed another variant. Pure functions, no I/O.

The exposure checks read them to name a flag change as the cause of their finding. They need no exposure question for
that, because the exposure answer already counts the users by the day of their first exposure. Each change names the
check of the health endpoint that reports it, so a finding of the exposure query can point at that check's finding.
"""

from collections.abc import Collection, Mapping
from datetime import date, datetime
from zoneinfo import ZoneInfo

from scipy.stats import chi2_contingency

from posthog.dataclasses import frozen

from products.experiments.backend.facade.contracts import ExperimentHealthCheckKey
from products.experiments.backend.health.condition_changes import ConditionsChangeShape, conditions_shape
from products.experiments.backend.health.context import FlagChange, FlagHistory, FlagHistoryNotChecked, HealthContext
from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.feature_flags.backend.facade.edits import BucketingChange, ConditionsChange, SplitChange

# The level of the sample ratio test, so that a change explains a finding only on evidence as strong as the finding's.
DIFFERS_ACROSS_CHANGE_P_VALUE = 0.001

# A save can change several things at once. Its split change then names the cause, because the split check's finding
# carries the move of the start date that every kind of change asks for.
_CHECK_ORDER = (
    ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN,
    ExperimentHealthCheckKey.RELEASE_CONDITIONS_CHANGED_MID_RUN,
    ExperimentHealthCheckKey.BUCKETING_CHANGED_MID_RUN,
)


@frozen
class VariantMove:
    """The last change after launch that can have given exposed users another variant."""

    check: ExperimentHealthCheckKey
    changed_at: datetime
    team_timezone: str

    @property
    def day(self) -> date:
        """The day of the change in the team's timezone, the timezone of the exposure answer's days."""
        return self.changed_at.astimezone(ZoneInfo(self.team_timezone)).date()

    def before(self, daily: Mapping[date, int]) -> int:
        """The users first exposed before the day of the change. Those of that day can be on either side, so neither
        side counts them."""
        return sum(count for day, count in daily.items() if day < self.day)

    def after(self, daily: Mapping[date, int]) -> int:
        return sum(count for day, count in daily.items() if day > self.day)


def differs_across_change(before: Mapping[str, int], after: Mapping[str, int]) -> bool:
    """Whether the users first exposed before a change and those first exposed after it fall into the keys in
    different shares."""
    keys = [key for key in before.keys() | after.keys() if before.get(key, 0) + after.get(key, 0) > 0]
    if len(keys) < 2 or sum(before.values()) == 0 or sum(after.values()) == 0:
        return False
    table = [[before.get(key, 0) for key in keys], [after.get(key, 0) for key in keys]]
    return float(chi2_contingency(table).pvalue) < DIFFERS_ACROSS_CHANGE_P_VALUE


def _check_of(change: FlagChange) -> ExperimentHealthCheckKey | None:
    match change:
        case SplitChange():
            return ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN
        case BucketingChange():
            return ExperimentHealthCheckKey.BUCKETING_CHANGED_MID_RUN
        case ConditionsChange():
            # A change that only moves users into or out of the flag gives nobody another variant.
            if conditions_shape(change.before, change.after) != ConditionsChangeShape.VARIANT_OVERRIDE_CHANGED:
                return None
            return ExperimentHealthCheckKey.RELEASE_CONDITIONS_CHANGED_MID_RUN


def last_variant_move(
    history: FlagHistory | FlagHistoryNotChecked | None,
    *,
    checks: Collection[ExperimentHealthCheckKey],
    ended_at: datetime | None,
) -> VariantMove | None:
    """The last change of the kinds that `checks` report, before the end. None without a readable history."""
    if not isinstance(history, FlagHistory | FlagHistoryNotChecked):
        return None
    moves = [
        (change.changed_at, -_CHECK_ORDER.index(check), check)
        for change in history.changes
        if (check := _check_of(change)) is not None
        and check in checks
        # After the end the results count no exposure, so a later change moved nobody in them.
        and (ended_at is None or change.changed_at <= ended_at)
    ]
    if not moves:
        return None
    changed_at, _, check = max(moves)
    return VariantMove(check=check, changed_at=changed_at, team_timezone=history.team_timezone)


@frozen
class MultipleVariantCause:
    """A flag change that explains the users exposed to more than one variant."""

    move: VariantMove
    multiple_before: int
    # The users in more than one variant among those first exposed after the day of the change, on the 0-100 scale.
    share_after: float


def multiple_variant_cause(ctx: HealthContext, *, threshold: float) -> MultipleVariantCause | None:
    """The last flag change that gave exposed users another variant, when it explains the users in more than one
    variant: among the users first exposed after its day, their share is at most `threshold`, and lower than among the
    users first exposed before it. Moving the start date past the change then leaves out most of them."""
    exposures = ctx.exposures
    events = ctx.exposure_events
    # With an activation, the exposure query dates a user by the activation, but the flag call before it assigned the
    # variant, so a user dated after the change can carry a variant from before it.
    if exposures is None or events is None or events.activation is not None:
        return None
    move = last_variant_move(ctx.flag_history, checks=_CHECK_ORDER, ended_at=ctx.ended_at)
    if move is None:
        return None
    daily = exposures.daily_exposures
    multiple = daily.get(MULTIPLE_VARIANT_KEY, {})
    before = {
        "multiple": move.before(multiple),
        "single": sum(move.before(counts) for variant, counts in daily.items() if variant != MULTIPLE_VARIANT_KEY),
    }
    after = {
        "multiple": move.after(multiple),
        "single": sum(move.after(counts) for variant, counts in daily.items() if variant != MULTIPLE_VARIANT_KEY),
    }
    total_before = sum(before.values())
    total_after = sum(after.values())
    if not total_before or not total_after:
        return None
    share_before = before["multiple"] / total_before * 100
    share_after = after["multiple"] / total_after * 100
    if share_after > threshold or share_after >= share_before or not differs_across_change(before, after):
        return None
    return MultipleVariantCause(move=move, multiple_before=before["multiple"], share_after=share_after)
