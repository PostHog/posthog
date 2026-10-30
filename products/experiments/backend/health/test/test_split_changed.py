from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from posthog.schema import MultipleVariantHandling

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
)
from products.experiments.backend.health.checks.flag_change_findings import flag_history_not_readable
from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.checks.srm import (
    reads_flag_history,
    reads_segments,
    segments_first_exposed_after,
    srm,
)
from products.experiments.backend.health.context import (
    ExposureEvents,
    ExposureSegment,
    ExposureTotals,
    FlagHistoryNotCheckedReason,
    HealthContext,
    parse_flag_state,
)
from products.experiments.backend.health.skips import (
    FLAG_DELETED,
    NEEDS_VARIANTS,
    NOT_AFTER_END,
    NOT_ON_ARCHIVED,
    CheckSkip,
    not_applicable,
)
from products.experiments.backend.health.test.factories import ENDED, RUNNING, RUNNING_CONTEXT, Status, flag_history
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureSegmentDimension
from products.feature_flags.backend.facade.edits import SplitChange, parse_variants

LAUNCHED_AT = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
FIRST_CHANGE_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)
FIRST_CHANGE = "September 12, 2026 at 3:04 PM CEST"
SECOND_CHANGE = "September 12, 2026 at 3:21 PM CEST"
THIRD_CHANGE = "September 12, 2026 at 3:38 PM CEST"
MIXED_ASSIGNMENTS = "A sample ratio mismatch or users in more than one variant can come from this change."

EVERYONE = [{"properties": [], "rollout_percentage": 100}]
TARGETED = [{"properties": [{"key": "plan", "value": "pro", "type": "person"}], "rollout_percentage": 100}]


def _split(*variants: tuple[str, float]) -> list[dict[str, Any]]:
    return [{"key": key, "rollout_percentage": share} for key, share in variants]


EVEN = _split(("control", 50), ("test", 50))
UNEVEN = _split(("control", 80), ("test", 20))
THREE_WAY = _split(("control", 34), ("test", 33), ("blue", 33))
BLUE_ZEROED = _split(("control", 50), ("test", 50), ("blue", 0))
SHIPPED = _split(("control", 0), ("test", 100))


def _context(
    *splits: list[dict[str, Any]],
    status: Status = RUNNING,
    groups: list[dict[str, Any]] = EVERYONE,
    exposed_before_first: bool | None = True,
    exposed_between: bool | None = None,
    launched_at: datetime = LAUNCHED_AT,
    first_change_at: datetime = FIRST_CHANGE_AT,
    archived: bool = False,
    deleted: bool = False,
    not_checked: FlagHistoryNotCheckedReason | None = None,
    exposed_units: int | None = None,
    counts_groups: bool = False,
) -> HealthContext:
    changes = [
        SplitChange(
            changed_at=first_change_at + timedelta(minutes=17 * index),
            before=parse_variants(before),
            after=parse_variants(after),
        )
        for index, (before, after) in enumerate(zip(splits, splits[1:]))
    ]
    return replace(
        RUNNING_CONTEXT,
        **status,
        archived=archived,
        flag=parse_flag_state(active=True, deleted=deleted, groups=groups, variants=splits[-1]),
        flag_history=flag_history(
            changes,
            launched_at=launched_at,
            exposed_before_first=exposed_before_first,
            exposed_between={ExperimentHealthFlagChangeKind.SPLIT: exposed_between},
            not_checked=not_checked,
            exposed_units_before_last={ExperimentHealthFlagChangeKind.SPLIT: exposed_units},
            counts_groups=counts_groups,
        ),
    )


def _split_code_finding(ctx: HealthContext) -> ExperimentHealthFinding | None:
    # The registry runs both checks, and a history the reader can't view gets the split check's code.
    outcomes = (flag_history_not_readable(ctx), split_changed_mid_run(ctx))
    return next((outcome for outcome in outcomes if isinstance(outcome, ExperimentHealthFinding)), None)


class TestSplitChangedMidRun(TestCase):
    @parameterized.expand(
        [
            (
                "rebalanced",
                _context(EVEN, UNEVEN),
                ("rebalanced", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "People exposed before the change may have switched variants, so the results mix two assignments. "
                f"Reset the experiment, or move its start date to {FIRST_CHANGE} to analyze only the people exposed "
                f"after the change. {MIXED_ASSIGNMENTS}",
            ),
            (
                "suggested_start_rounded_up_to_the_next_minute",
                _context(EVEN, UNEVEN, first_change_at=FIRST_CHANGE_AT + timedelta(seconds=45)),
                ("rebalanced", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "People exposed before the change may have switched variants, so the results mix two assignments. "
                "Reset the experiment, or move its start date to September 12, 2026 at 3:05 PM CEST to analyze "
                f"only the people exposed after the change. {MIXED_ASSIGNMENTS}",
            ),
            (
                "rebalanced_with_unknown_exposure",
                _context(EVEN, UNEVEN, exposed_before_first=None),
                ("rebalanced", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "The change came 3 hours after launch. "
                "People exposed before the change may have switched variants, so the results mix two assignments. "
                f"Reset the experiment, or move its start date to {FIRST_CHANGE} to analyze only the people exposed "
                f"after the change. {MIXED_ASSIGNMENTS}",
            ),
            (
                "rebalanced_before_4_people",
                _context(EVEN, UNEVEN, exposed_units=4),
                ("rebalanced", ExperimentHealthFindingSeverity.INFO, "E3"),
                f"The split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "The change came 3 hours after launch, when 4 people had been exposed. Move the start date to "
                f"{FIRST_CHANGE} so the results count only exposures after it.",
            ),
            (
                "rebalanced_before_5_people",
                _context(EVEN, UNEVEN, exposed_units=5),
                ("rebalanced", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "People exposed before the change may have switched variants, so the results mix two assignments. "
                f"Reset the experiment, or move its start date to {FIRST_CHANGE} to analyze only the people exposed "
                f"after the change. {MIXED_ASSIGNMENTS}",
            ),
            (
                "rebalanced_before_any_group",
                _context(EVEN, UNEVEN, exposed_units=0, counts_groups=True),
                ("rebalanced", ExperimentHealthFindingSeverity.INFO, "E3"),
                f"The split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "The change came 3 hours after launch, when no group had been exposed.",
            ),
            (
                "variant_zeroed_before_4_groups",
                _context(THREE_WAY, BLUE_ZEROED, exposed_units=4, counts_groups=True),
                ("variant_zeroed", ExperimentHealthFindingSeverity.INFO, "E3"),
                f'Variant "blue" was set to 0% on {FIRST_CHANGE} (from control 34% / test 33% / blue 33% to '
                "control 50% / test 50% / blue 0%). The change came 3 hours after launch, when 4 groups had been "
                f"exposed. Move the start date to {FIRST_CHANGE} so the results count only exposures after it. "
                'No new users get "blue".',
            ),
            (
                "variant_rolled_out_before_1_person",
                _context(EVEN, SHIPPED, groups=TARGETED, exposed_units=1),
                ("variant_rolled_out", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f'Variant "test" was set to 100% of the split on {FIRST_CHANGE}, while the experiment is still '
                'running. From then on, the split assigns everyone to variant "test". End the experiment with a '
                f"conclusion, or restore the split. {MIXED_ASSIGNMENTS}",
            ),
            (
                "variant_removed",
                _context(THREE_WAY, EVEN),
                ("variant_removed", ExperimentHealthFindingSeverity.WARNING, "E4"),
                f'Variant "blue" was removed on {FIRST_CHANGE} (from control 34% / test 33% / blue 33% to '
                'control 50% / test 50%). The results leave out people who saw only "blue", and people who had '
                f'"blue" may now get another variant. Reset the experiment, or move its start date to {FIRST_CHANGE}. '
                f"{MIXED_ASSIGNMENTS}",
            ),
            (
                "variant_added",
                _context(EVEN, THREE_WAY),
                ("variant_added", ExperimentHealthFindingSeverity.WARNING, "E4"),
                f'Variant "blue" was added on {FIRST_CHANGE} (from control 50% / test 50% to control 34% / '
                "test 33% / blue 33%). People exposed before the change may have switched variants. Reset the "
                f"experiment, or move its start date to {FIRST_CHANGE}. {MIXED_ASSIGNMENTS}",
            ),
            (
                "variant_zeroed",
                _context(THREE_WAY, BLUE_ZEROED),
                ("variant_zeroed", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f'Variant "blue" was set to 0% on {FIRST_CHANGE} (from control 34% / test 33% / blue 33% to '
                "control 50% / test 50% / blue 0%). People exposed before the change may have switched variants, "
                f'and no new users get "blue". Reset the experiment, or move its start date to {FIRST_CHANGE}. '
                f"{MIXED_ASSIGNMENTS}",
            ),
            (
                "reordered",
                _context(EVEN, _split(("test", 50), ("control", 50))),
                ("reordered", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The order of the variants changed on {FIRST_CHANGE} (from control 50% / test 50% to test 50% / "
                "control 50%). The order decides who gets which variant, so people exposed before the change may "
                f"have switched variants. Reset the experiment, or move its start date to {FIRST_CHANGE}. "
                f"{MIXED_ASSIGNMENTS}",
            ),
            (
                "variant_rolled_out_inside_targeted_conditions",
                _context(EVEN, SHIPPED, groups=TARGETED),
                ("variant_rolled_out", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f'Variant "test" was set to 100% of the split on {FIRST_CHANGE}, while the experiment is still '
                'running. From then on, the split assigns everyone to variant "test". End the experiment with a '
                f"conclusion, or restore the split. {MIXED_ASSIGNMENTS}",
            ),
            (
                "several_changes_days_after_launch",
                _context(
                    EVEN,
                    _split(("control", 70), ("test", 30)),
                    _split(("control", 60), ("test", 40)),
                    UNEVEN,
                    launched_at=LAUNCHED_AT - timedelta(days=8),
                ),
                ("rebalanced", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split changed 3 times between {FIRST_CHANGE} and {THIRD_CHANGE}, from control 50% / "
                "test 50% to control 80% / test 20%. The first change came 8 days after launch. People exposed "
                "before the changes may have switched variants, so the results mix two assignments. Reset the "
                f"experiment, or move its start date to {THIRD_CHANGE} to analyze only the people exposed after the "
                "changes. A sample ratio mismatch or users in more than one variant can come from these changes.",
            ),
            (
                "reverted_with_exposures_in_between",
                _context(EVEN, SHIPPED, EVEN, exposed_between=True),
                ("reverted", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split was set to control 0% / test 100% on {FIRST_CHANGE} and set back to control 50% / "
                f"test 50% on {SECOND_CHANGE}. People exposed in between may have switched variants. Move the start "
                f"date to {SECOND_CHANGE}, or reset the experiment.",
            ),
            (
                "reverted_before_4_people",
                _context(EVEN, SHIPPED, EVEN, exposed_between=True, exposed_units=4),
                ("reverted", ExperimentHealthFindingSeverity.INFO, "E3"),
                f"The split was set to control 0% / test 100% on {FIRST_CHANGE} and set back to control 50% / "
                f"test 50% on {SECOND_CHANGE}. The last change came 3 hours after launch, when 4 people had been "
                f"exposed. Move the start date to {SECOND_CHANGE} so the results count only exposures after it.",
            ),
            (
                "reverted_with_unknown_exposures_in_between",
                _context(EVEN, SHIPPED, EVEN, exposed_between=None),
                ("reverted", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split was set to control 0% / test 100% on {FIRST_CHANGE} and set back to control 50% / "
                f"test 50% on {SECOND_CHANGE}. People exposed in between may have switched variants. Move the start "
                f"date to {SECOND_CHANGE}, or reset the experiment.",
            ),
            (
                "reverted_without_exposures_in_between",
                _context(EVEN, SHIPPED, EVEN, exposed_between=False),
                ("reverted", ExperimentHealthFindingSeverity.INFO, "E3"),
                f"The split was set to control 0% / test 100% on {FIRST_CHANGE} and set back 17 minutes later. "
                "Nobody was exposed in between.",
            ),
            (
                "reverted_through_a_flag_without_variants",
                _context(EVEN, [], EVEN, exposed_between=True),
                ("reverted", ExperimentHealthFindingSeverity.WARNING, "E3"),
                f"The split was set to no variants on {FIRST_CHANGE} and set back to control 50% / test 50% on "
                f"{SECOND_CHANGE}. People exposed in between may have switched variants. Move the start date to "
                f"{SECOND_CHANGE}, or reset the experiment.",
            ),
        ]
    )
    def test_reports_the_net_change(
        self,
        _name: str,
        ctx: HealthContext,
        expected: tuple[str, ExperimentHealthFindingSeverity, str],
        expected_detail: str,
    ) -> None:
        finding = split_changed_mid_run(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(finding.code, ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN)
        self.assertEqual((finding.subcode, finding.severity, finding.diagnostic_ref), expected)
        self.assertEqual(finding.detail, expected_detail)
        self.assertEqual(finding.actions, (ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,))

    @parameterized.expand(
        [
            (
                "unknown_exposure",
                _context(EVEN, UNEVEN, exposed_before_first=None),
                None,
                {
                    "change_count": 1,
                    "first_changed_at": "2026-09-12T13:04:00+00:00",
                    "last_changed_at": "2026-09-12T13:04:00+00:00",
                    "from": "control 50% / test 50%",
                    "to": "control 80% / test 20%",
                    "exposed_before_change": None,
                    "seconds_after_launch": 11040,
                    "units_exposed_before_last_change": None,
                },
            ),
            (
                "few_exposed",
                _context(EVEN, UNEVEN, exposed_units=4),
                None,
                {
                    "change_count": 1,
                    "first_changed_at": "2026-09-12T13:04:00+00:00",
                    "last_changed_at": "2026-09-12T13:04:00+00:00",
                    "from": "control 50% / test 50%",
                    "to": "control 80% / test 20%",
                    "exposed_before_change": True,
                    "seconds_after_launch": 11040,
                    "units_exposed_before_last_change": 4,
                },
            ),
            (
                "not_checked",
                _context(EVEN, UNEVEN, not_checked=FlagHistoryNotCheckedReason.EXPOSURE_FILTERS),
                "exposure_filters",
                {
                    "change_count": 1,
                    "first_changed_at": "2026-09-12T13:04:00+00:00",
                    "last_changed_at": "2026-09-12T13:04:00+00:00",
                    "from": "control 50% / test 50%",
                    "to": "control 80% / test 20%",
                    "exposed_before_change": None,
                    "seconds_after_launch": 11040,
                },
            ),
            (
                "not_checked_without_history_access",
                _context(EVEN, not_checked=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS),
                "no_history_access",
                {},
            ),
        ]
    )
    def test_evidence(self, _name: str, ctx: HealthContext, reason: str | None, expected: dict[str, Any]) -> None:
        finding = _split_code_finding(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual((finding.reason, finding.evidence), (reason, expected))

    @parameterized.expand(
        [
            (
                "exposure_filters",
                _context(EVEN, UNEVEN, not_checked=FlagHistoryNotCheckedReason.EXPOSURE_FILTERS),
                f"The variant split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "This check can't tell whether anyone was exposed before the change, because the exposure criteria "
                "filter by properties. Review the change in the flag history.",
            ),
            (
                "exposure_action_after_several_changes",
                _context(
                    EVEN,
                    _split(("control", 70), ("test", 30)),
                    UNEVEN,
                    not_checked=FlagHistoryNotCheckedReason.EXPOSURE_ACTION,
                ),
                "The variant split changed 2 times after launch, from control 50% / test 50% to control 80% / "
                f"test 20%, last on {SECOND_CHANGE}. This check can't tell whether anyone was exposed before the "
                "changes, because exposures come from an action. Review the changes in the flag history.",
            ),
            (
                "exposure_criteria_after_a_split_set_back",
                _context(EVEN, SHIPPED, EVEN, not_checked=FlagHistoryNotCheckedReason.EXPOSURE_CRITERIA),
                "The variant split changed 2 times after launch and was set back to control 50% / test 50% on "
                f"{SECOND_CHANGE}. This check can't tell whether anyone was exposed before the changes, because the "
                "exposure criteria can't be read. Review the changes in the flag history.",
            ),
            (
                "no_query_access",
                _context(EVEN, UNEVEN, not_checked=FlagHistoryNotCheckedReason.NO_QUERY_ACCESS),
                f"The variant split changed from control 50% / test 50% to control 80% / test 20% on {FIRST_CHANGE}. "
                "This check can't tell whether anyone was exposed before the change, because this API key can't "
                "query events. Add the query:read scope to this API key, or review the change in the flag history.",
            ),
            (
                "no_history_access",
                _context(EVEN, not_checked=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS),
                "This check can't see whether the flag's variant split, key, bucketing or release conditions changed "
                "after launch, because you can't view the linked feature flag's history. Viewing the history needs "
                "viewer access to the flag and, with an API key, the activity_log:read scope.",
                (),
                "The flag history was not checked",
            ),
            (
                "too_many_saves",
                _context(EVEN, not_checked=FlagHistoryNotCheckedReason.TOO_MANY_SAVES),
                "This check can't see whether the flag's variant split, key, bucketing or release conditions changed "
                "after launch, because the flag was saved more than 100 times since launch. Review the flag history.",
                (ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,),
                "The flag history was not checked",
            ),
        ]
    )
    def test_reports_split_changes_that_were_not_checked(
        self,
        _name: str,
        ctx: HealthContext,
        expected_detail: str,
        expected_actions: tuple[ExperimentHealthFindingActionKind, ...] = (
            ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,
        ),
        expected_title: str = "Variant split changes were not checked",
    ) -> None:
        finding = _split_code_finding(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(
            (finding.code, finding.subcode, finding.severity, finding.diagnostic_ref, finding.title),
            (
                ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN,
                "not_checked",
                ExperimentHealthFindingSeverity.INFO,
                "E3",
                expected_title,
            ),
        )
        self.assertEqual(finding.detail, expected_detail)
        self.assertEqual(finding.actions, expected_actions)

    @parameterized.expand(
        [
            ("ended", _context(EVEN, UNEVEN, status=ENDED), not_applicable(NOT_AFTER_END)),
            ("archived", _context(EVEN, UNEVEN, archived=True), not_applicable(NOT_ON_ARCHIVED)),
            ("deleted_flag", _context(EVEN, UNEVEN, deleted=True), not_applicable(FLAG_DELETED)),
            ("nobody_exposed_before_any_change", _context(EVEN), None),
            (
                "flag_without_variants_reported_by_flag_variants_mismatch",
                _context(EVEN, []),
                not_applicable(NEEDS_VARIANTS),
            ),
            (
                "not_checked_on_an_ended_experiment",
                _context(EVEN, status=ENDED, not_checked=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS),
                not_applicable(NOT_AFTER_END),
            ),
        ]
    )
    def test_no_finding(self, _name: str, ctx: HealthContext, expected: CheckSkip | None) -> None:
        self.assertEqual((_split_code_finding(ctx), split_changed_mid_run(ctx)), (None, expected))

    @parameterized.expand(
        [
            ("one_change", _context(EVEN, SHIPPED), FIRST_CHANGE, "control 50% / test 50%"),
            (
                "rollout_after_a_rebalance",
                _context(EVEN, _split(("control", 70), ("test", 30)), SHIPPED),
                SECOND_CHANGE,
                "control 70% / test 30%",
            ),
            (
                "rollout_not_checked",
                _context(EVEN, SHIPPED, not_checked=FlagHistoryNotCheckedReason.EXPOSURE_FILTERS),
                FIRST_CHANGE,
                "control 50% / test 50%",
            ),
        ]
    )
    def test_shipped_finding_reports_a_rollout_to_everyone(
        self, _name: str, ctx: HealthContext, rolled_out_at: str, split_before: str
    ) -> None:
        shipped = flag_state(ctx)

        self.assertIsNone(split_changed_mid_run(ctx))
        assert isinstance(shipped, ExperimentHealthFinding)
        self.assertEqual(shipped.code, ExperimentHealthFindingCode.VARIANT_SHIPPED_WHILE_RUNNING)
        self.assertEqual(
            shipped.detail,
            f'Variant "test" is rolled out to 100% of users. It has been at 100% since {rolled_out_at}, and the '
            f"split was {split_before} before. The experiment is not comparing variants. End the experiment "
            "with a conclusion, or adjust the variant distribution of the linked feature flag to resume proper A/B "
            "testing.",
        )


def _totals(after_change: dict[str, int], *, counts_groups: bool = False) -> ExposureTotals:
    # Exposed under the 50/50 split on the day of the change, then the given ones on the next day under 80/20.
    before = {"control": 500, "test": 500}
    total_exposures = {variant: before[variant] + after_change[variant] for variant in before}
    whole_run = sum(total_exposures.values())
    return ExposureTotals(
        total_exposures=total_exposures,
        multiple_variant_handling=MultipleVariantHandling.EXCLUDE,
        sample_ratio_mismatch_p_value=0.00001,
        sample_ratio_expected={"control": 0.8 * whole_run, "test": 0.2 * whole_run},
        daily_exposures={
            variant: {FIRST_CHANGE_AT.date(): before[variant], date(2026, 9, 13): after_change[variant]}
            for variant in before
        },
        hours_since_launch=72,
        counts_groups=counts_groups,
    )


MATCHES_THE_NEW_SPLIT = {"control": 400, "test": 100}
REVERSED_SPLIT = _split(("test", 20), ("control", 80))


ACTIVATION_EVENTS = ExposureEvents(
    custom_event=None,
    required_flag_key="flag",
    variant_property="$feature_flag_response",
    flag_key_filters=(),
    activation="checkout",
)
PLAIN_TITLE = "Users are not split across variants as configured"


class TestSrmAfterSplitChange(TestCase):
    @parameterized.expand(
        [
            (
                "retest_passes",
                _context(EVEN, UNEVEN, exposed_units=5),
                _totals(MATCHES_THE_NEW_SPLIT),
                (
                    "split_changed",
                    "The users first exposed after the day of the change match the current split (p = 1).",
                ),
            ),
            (
                "retest_fails",
                _context(EVEN, UNEVEN, exposed_units=5),
                _totals({"control": 250, "test": 250}),
                ("split_changed", "don't match the current split either (p < 0.001), so look for another cause too."),
            ),
            (
                "retest_fails_in_one_library",
                _context(EVEN, UNEVEN, exposed_units=5),
                replace(
                    _totals({"control": 250, "test": 250}),
                    segments=(
                        ExposureSegment(
                            dimension=ExposureSegmentDimension.LIBRARY,
                            value="web",
                            exposed_by_variant={"control": 800, "test": 200},
                        ),
                        ExposureSegment(
                            dimension=ExposureSegmentDimension.LIBRARY,
                            value="posthog-node",
                            exposed_by_variant={"control": 50, "test": 450},
                        ),
                    ),
                ),
                (
                    "split_changed",
                    "so look for another cause too. The mismatch comes from users whose first exposure was sent by the "
                    '"posthog-node" library. Check that the code there sends the exposure for every user in every '
                    "variant. Follow the steps in",
                ),
            ),
            (
                "too_few_for_a_retest",
                _context(EVEN, UNEVEN, exposed_units=5),
                _totals({"control": 40, "test": 10}),
                ("split_changed", "Too few users were first exposed after the day of the change to test them alone."),
            ),
            (
                "activation_dates_users_after_their_flag_call",
                replace(_context(EVEN, UNEVEN, exposed_units=5), exposure_events=ACTIVATION_EVENTS),
                _totals(MATCHES_THE_NEW_SPLIT),
                ("split_changed", "so the users exposed after the change can't be tested alone."),
            ),
            (
                "groups",
                _context(EVEN, UNEVEN, exposed_units=5),
                _totals(MATCHES_THE_NEW_SPLIT, counts_groups=True),
                ("split_changed", "Groups are not split as configured after a split change"),
            ),
            (
                "reorder",
                _context(UNEVEN, REVERSED_SPLIT, exposed_units=5),
                _totals(MATCHES_THE_NEW_SPLIT),
                ("split_changed", "which can cause this."),
            ),
            (
                "change_before_4_people",
                _context(EVEN, UNEVEN, exposed_units=4),
                _totals(MATCHES_THE_NEW_SPLIT),
                (None, PLAIN_TITLE),
            ),
            (
                "history_not_checked",
                _context(EVEN, UNEVEN, not_checked=FlagHistoryNotCheckedReason.EXPOSURE_FILTERS),
                _totals(MATCHES_THE_NEW_SPLIT),
                (None, PLAIN_TITLE),
            ),
            (
                "history_not_loaded",
                replace(_context(EVEN, UNEVEN, exposed_units=5), flag_history=None),
                _totals(MATCHES_THE_NEW_SPLIT),
                (None, PLAIN_TITLE),
            ),
        ]
    )
    def test_names_a_split_change_as_the_likely_cause(
        self, _name: str, ctx: HealthContext, totals: ExposureTotals, expected: tuple[str | None, str]
    ) -> None:
        outcome = srm(replace(ctx, exposures=totals))

        assert isinstance(outcome, ExperimentHealthFinding)
        subcode, text = expected
        self.assertEqual((outcome.subcode, outcome.severity), (subcode, ExperimentHealthFindingSeverity.WARNING))
        self.assertIn(text, f"{outcome.title} {outcome.detail}")

    @parameterized.expand(
        [
            ("failing_test", RUNNING_CONTEXT, MATCHES_THE_NEW_SPLIT, 0.00001, (True, True, None)),
            ("passing_test", RUNNING_CONTEXT, MATCHES_THE_NEW_SPLIT, 0.01, (False, False, None)),
            (
                "split_change_explains_it",
                _context(EVEN, UNEVEN, exposed_units=5),
                MATCHES_THE_NEW_SPLIT,
                0.00001,
                (True, False, FIRST_CHANGE_AT.date()),
            ),
            (
                "split_change_with_a_failed_retest",
                _context(EVEN, UNEVEN, exposed_units=5),
                {"control": 250, "test": 250},
                0.00001,
                (True, True, FIRST_CHANGE_AT.date()),
            ),
            (
                "activation",
                replace(RUNNING_CONTEXT, exposure_events=ACTIVATION_EVENTS),
                MATCHES_THE_NEW_SPLIT,
                0.00001,
                (True, False, None),
            ),
        ]
    )
    def test_reads_the_flag_history_and_the_segments_only_for_a_mismatch(
        self,
        _name: str,
        ctx: HealthContext,
        after_change: dict[str, int],
        p_value: float,
        expected: tuple[bool, bool, date | None],
    ) -> None:
        ctx = replace(ctx, exposures=replace(_totals(after_change), sample_ratio_mismatch_p_value=p_value))

        self.assertEqual((reads_flag_history(ctx), reads_segments(ctx), segments_first_exposed_after(ctx)), expected)

    def test_names_the_cause_the_evidence_and_the_next_step(self) -> None:
        outcome = srm(replace(_context(EVEN, UNEVEN, exposed_units=5), exposures=_totals(MATCHES_THE_NEW_SPLIT)))

        assert isinstance(outcome, ExperimentHealthFinding)
        self.assertEqual(outcome.title, "Users are not split as configured after a split change")
        self.assertEqual(
            outcome.detail,
            "The distribution of users across variants doesn't match your current rollout percentages (p < 0.001). "
            "The variant split changed after launch while users were exposed, and some of them got their variants "
            "from another split, which can cause this. The users first exposed after the day of the change match the "
            'current split (p = 1). Follow the steps in "The variant split changed after launch" to fix the results.',
        )
