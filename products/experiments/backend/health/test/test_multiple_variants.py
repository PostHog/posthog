from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthCheckKey,
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
)
from products.experiments.backend.health.checks.bias_risk import bias_risk_multiple_excluded
from products.experiments.backend.health.checks.multiple_variants import multiple_variants_share, reads_flag_changes
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposureTotals,
    FlagChange,
    HealthContext,
    parse_flag_state,
)
from products.experiments.backend.health.test.factories import ENDED, RUNNING_CONTEXT, flag_history
from products.feature_flags.backend.facade.edits import (
    ConditionsChange,
    SplitChange,
    parse_release_conditions,
    parse_variants,
)

CHANGED_AT = datetime(2026, 11, 7, 5, 26, 30, tzinfo=UTC)
EVEN = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
UNEVEN = [{"key": "control", "rollout_percentage": 80}, {"key": "test", "rollout_percentage": 20}]
EVERYONE = {"properties": [], "rollout_percentage": 100}
GERMANY = {
    "properties": [{"key": "$geoip_country_code", "value": ["DE"], "operator": "exact", "type": "person"}],
    "rollout_percentage": 100,
}
TARGETED = {
    "properties": [{"key": "plan", "value": ["pro"], "operator": "exact", "type": "person"}],
    "rollout_percentage": 100,
}

SPLIT_CHANGE = SplitChange(changed_at=CHANGED_AT, before=parse_variants(EVEN), after=parse_variants(UNEVEN))


def _conditions_change(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> ConditionsChange:
    return ConditionsChange(
        changed_at=CHANGED_AT,
        before=parse_release_conditions(before, variant_keys=["control", "test"]),
        after=parse_release_conditions(after, variant_keys=["control", "test"]),
    )


OVERRIDE_REMOVED = _conditions_change([{**GERMANY, "variant": "test"}, EVERYONE], [GERMANY, EVERYONE])


def _exposures(multiple_before: int, multiple_after: int, *, counts_groups: bool = False) -> ExposureTotals:
    # 1,000 users first exposed on a day before the change, 50 on its day and 1,000 on a day after it.
    days = {
        date(2026, 11, 5): (1000 - multiple_before, multiple_before),
        date(2026, 11, 7): (45, 5),
        date(2026, 11, 9): (1000 - multiple_after, multiple_after),
    }
    daily = {
        "control": {day: single // 2 for day, (single, _) in days.items()},
        "test": {day: single - single // 2 for day, (single, _) in days.items()},
        "$multiple": {day: multiple for day, (_, multiple) in days.items()},
    }
    return ExposureTotals(
        total_exposures={variant: sum(counts.values()) for variant, counts in daily.items()},
        multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
        sample_ratio_mismatch_p_value=None,
        sample_ratio_expected={},
        daily_exposures=daily,
        hours_since_launch=200,
        counts_groups=counts_groups,
        filters_test_accounts=False,
        has_positive_test_account_filter=False,
    )


def _context(
    changes: list[FlagChange], exposures: ExposureTotals, variants: list[dict[str, Any]] = UNEVEN
) -> HealthContext:
    return replace(
        RUNNING_CONTEXT,
        flag=parse_flag_state(active=True, deleted=False, groups=[EVERYONE], variants=variants),
        flag_history=flag_history(changes, start_date=CHANGED_AT - timedelta(days=5)),
        exposures=exposures,
    )


class TestMultipleVariantsFlagChange(TestCase):
    def test_leads_with_a_flag_change_that_explains_the_share(self) -> None:
        finding = multiple_variants_share(_context([SPLIT_CHANGE], _exposures(150, 10)))

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.title, finding.actions, finding.caused_by, finding.evidence["suggested_start_date"]),
            (
                "8.0% of users were exposed to more than one variant, so the results leave them out",
                (ExperimentHealthFindingActionKind.MOVE_START_DATE,),
                ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN,
                "2026-11-07T05:27:00+00:00",
            ),
        )
        self.assertEqual(
            finding.detail,
            "8.0% of users (165) were exposed to multiple variants, so the results leave them out. The exposures "
            "table lists them as $multiple. If a variant changes how often users log in, each variant loses a "
            "different group of users, and the results can be biased.\n\n"
            "At least 150 of them were first exposed before the variant split changed on November 7, 2026 at 6:26 AM "
            "CET, and that change can give users who were already exposed another variant. Among the users first "
            "exposed after the day of the change, 1.0% were exposed to multiple variants. Move the start date to "
            "November 7, 2026 at 6:27 AM CET so the results count only exposures after the change.\n\n"
            "If the share grows again among users exposed later, one person has more than one ID: an anonymous ID "
            "before login and another after, an ID for each device, a new ID after reset(), or a different ID on "
            "your server than in the browser. Identify users before your code evaluates the flag, call reset() only "
            "at logout, and send the same ID from your server.",
        )

    @parameterized.expand(
        [
            (
                "override_removed",
                [OVERRIDE_REMOVED],
                _exposures(150, 10),
                ExperimentHealthCheckKey.RELEASE_CONDITIONS_CHANGED_MID_RUN,
            ),
            (
                "split_and_conditions_in_one_save",
                [SPLIT_CHANGE, OVERRIDE_REMOVED],
                _exposures(150, 10),
                ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN,
            ),
            ("share_stays_high_after_the_change", [SPLIT_CHANGE], _exposures(150, 80), None),
            ("share_as_high_before_the_change", [SPLIT_CHANGE], _exposures(50, 50), None),
            (
                "change_that_gives_nobody_another_variant",
                [_conditions_change([EVERYONE], [TARGETED, EVERYONE])],
                _exposures(150, 10),
                None,
            ),
            ("no_change", [], _exposures(150, 10), None),
        ]
    )
    def test_names_a_flag_change_only_when_it_explains_the_share(
        self,
        _name: str,
        changes: list[FlagChange],
        exposures: ExposureTotals,
        caused_by: ExperimentHealthCheckKey | None,
    ) -> None:
        finding = multiple_variants_share(_context(changes, exposures))

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.caused_by, finding.actions),
            (caused_by, (ExperimentHealthFindingActionKind.MOVE_START_DATE,) if caused_by else ()),
        )

    @parameterized.expand(
        [
            (
                "activation_dates_users_after_their_flag_call",
                {
                    "exposure_events": ExposureEvents(
                        custom_event=None,
                        required_flag_key="flag",
                        variant_property="$feature_flag_response",
                        flag_key_filters=(),
                        activation="checkout",
                    )
                },
            ),
            ("change_after_the_end", {**ENDED, "ended_at": CHANGED_AT - timedelta(hours=1)}),
            ("history_not_loaded", {"flag_history": None}),
        ]
    )
    def test_names_no_change_it_cant_compare(self, _name: str, changes: dict[str, Any]) -> None:
        finding = multiple_variants_share(replace(_context([SPLIT_CHANGE], _exposures(150, 10)), **changes))

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertIsNone(finding.caused_by)

    def test_bias_names_a_flag_change_by_its_own_threshold(self) -> None:
        explained = bias_risk_multiple_excluded(_context([SPLIT_CHANGE], _exposures(150, 0)))
        not_explained = bias_risk_multiple_excluded(_context([SPLIT_CHANGE], _exposures(150, 10)))

        assert isinstance(explained, ExperimentHealthFinding) and isinstance(not_explained, ExperimentHealthFinding)
        self.assertEqual(
            (explained.caused_by, not_explained.caused_by), (ExperimentHealthCheckKey.SPLIT_CHANGED_MID_RUN, None)
        )

    @parameterized.expand(
        [
            ("share_above_the_line", _exposures(150, 10), UNEVEN, True),
            ("bias_on_an_uneven_split", _exposures(20, 0), UNEVEN, True),
            ("low_share_on_an_even_split", _exposures(20, 0), EVEN, False),
        ]
    )
    def test_loads_the_flag_changes_only_for_a_finding(
        self, _name: str, exposures: ExposureTotals, variants: list[dict[str, Any]], expected: bool
    ) -> None:
        self.assertEqual(reads_flag_changes(_context([], exposures, variants)), expected)
