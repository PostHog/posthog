from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckStatus,
    ExperimentHealthFinding,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.unserved_variants import (
    FLAG_OFF,
    VARIANT_NOT_SERVED,
    unserved_variant_exposures,
)
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposureTotals,
    FlagState,
    HealthContext,
    ReachableCondition,
)
from products.experiments.backend.health.skips import CheckSkip
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT
from products.feature_flags.backend.facade.edits import FlagVariant

SAVED_AT = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
SAVE_DAY = date(2026, 10, 10)
DAY_AFTER = date(2026, 10, 11)
EVERYONE = ReachableCondition(number=1, pinned_variant=None, variant_property=None, includes_everyone=True)
FLAG = FlagState(
    active=True,
    deleted=False,
    release_groups=(),
    variants=(FlagVariant(key="control", rollout_percentage=0), FlagVariant(key="test", rollout_percentage=100)),
    reachable_conditions=(EVERYONE,),
    saved_at=SAVED_AT,
)
TOTALS = ExposureTotals(
    total_exposures={},
    multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
    sample_ratio_mismatch_p_value=None,
    sample_ratio_expected={},
    daily_exposures={},
    hours_since_launch=240,
    counts_groups=False,
    filters_test_accounts=False,
    has_positive_test_account_filter=False,
)
SPLIT = (FlagVariant(key="control", rollout_percentage=50), FlagVariant(key="test", rollout_percentage=50))


def _context(daily: dict[str, dict[date, int]], **changes: Any) -> HealthContext:
    flag = replace(FLAG, **changes.pop("flag", {}))
    return replace(RUNNING_CONTEXT, flag=flag, exposures=replace(TOTALS, daily_exposures=daily), **changes)


def _outcome(ctx: HealthContext) -> tuple[str | None, int] | ExperimentHealthCheckStatus | None:
    outcome = unserved_variant_exposures(ctx)
    if isinstance(outcome, ExperimentHealthFinding):
        return outcome.subcode, int(outcome.evidence["unserved_exposed_count"] or 0)
    if isinstance(outcome, CheckSkip):
        return outcome.status
    return outcome


class TestUnservedVariantExposures(TestCase):
    @parameterized.expand(
        [
            (
                "a_variant_without_a_share",
                {"control": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                {},
                (VARIANT_NOT_SERVED, 30),
            ),
            (
                "a_variant_that_no_condition_sets_when_every_condition_pins",
                {"control": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                {
                    "flag": {
                        "variants": SPLIT,
                        "reachable_conditions": (
                            ReachableCondition(number=1, pinned_variant="test", variant_property=None),
                        ),
                    }
                },
                (VARIANT_NOT_SERVED, 30),
            ),
            (
                "the_flag_is_off",
                {"control": {DAY_AFTER: 40}, "test": {DAY_AFTER: 2}},
                {"flag": {"active": False, "variants": SPLIT}},
                (FLAG_OFF, 42),
            ),
            (
                "users_first_exposed_on_the_day_of_the_save_can_have_the_old_setup",
                {"control": {SAVE_DAY: 30}, "test": {SAVE_DAY: 70, DAY_AFTER: 70}},
                {},
                None,
            ),
            (
                "the_day_of_the_save_is_the_team_day",
                {"control": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                # 23:30 UTC is already the next day in Berlin.
                {"flag": {"saved_at": datetime(2026, 10, 10, 23, 30, tzinfo=UTC)}},
                None,
            ),
            (
                "users_in_multiple_variants_have_no_variant",
                {"$multiple": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                {},
                None,
            ),
            ("too_few_users", {"control": {DAY_AFTER: 4}, "test": {DAY_AFTER: 70}}, {}, None),
            ("a_small_share_of_the_new_users", {"control": {DAY_AFTER: 10}, "test": {DAY_AFTER: 1990}}, {}, None),
            (
                "a_zero_rollout_is_left_to_the_flag_state_check",
                {"control": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                {"flag": {"reachable_conditions": ()}},
                ExperimentHealthCheckStatus.NOT_APPLICABLE,
            ),
            (
                "an_activation_dates_users_after_the_flag_call",
                {"control": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                {
                    "exposure_events": ExposureEvents(
                        custom_event=None,
                        required_flag_key="flag",
                        variant_property="$feature_flag_response",
                        flag_key_filters=(),
                        activation="signed_up",
                    )
                },
                ExperimentHealthCheckStatus.NOT_APPLICABLE,
            ),
            (
                "the_time_of_the_save_is_unknown",
                {"control": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                {"flag": {"saved_at": None}},
                ExperimentHealthCheckStatus.NOT_CHECKED,
            ),
            (
                "after_the_end",
                {"control": {DAY_AFTER: 30}, "test": {DAY_AFTER: 70}},
                {"is_running": False, "has_ended": True},
                ExperimentHealthCheckStatus.NOT_APPLICABLE,
            ),
        ]
    )
    def test_unserved_variant_exposures(
        self,
        _name: str,
        daily: dict[str, dict[date, int]],
        changes: dict[str, Any],
        expected: tuple[str | None, int] | ExperimentHealthCheckStatus | None,
    ) -> None:
        self.assertEqual(_outcome(_context(daily, **changes)), expected)

    @parameterized.expand(
        [
            ("one_variant_holds_them", {"control": {DAY_AFTER: 40}, "test": {DAY_AFTER: 2}}, True),
            ("they_spread_over_the_variants", {"control": {DAY_AFTER: 21}, "test": {DAY_AFTER: 21}}, False),
        ]
    )
    def test_a_default_value_in_one_variant_is_a_warning_and_a_spread_assignment_is_info(
        self, _name: str, daily: dict[str, dict[date, int]], names_the_default: bool
    ) -> None:
        outcome = unserved_variant_exposures(_context(daily, flag={"active": False, "variants": SPLIT}))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(
            (
                outcome.title,
                outcome.severity,
                'in "control", which usually means that your code sends it' in outcome.detail,
            ),
            (
                "Users are exposed while the feature flag is off",
                ExperimentHealthFindingSeverity.WARNING if names_the_default else ExperimentHealthFindingSeverity.INFO,
                names_the_default,
            ),
        )
