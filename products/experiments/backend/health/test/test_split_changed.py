from datetime import UTC, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
)
from products.experiments.backend.health.checks.flag_state import flag_state
from products.experiments.backend.health.checks.split_changed import split_changed_mid_run
from products.experiments.backend.health.context import (
    HealthContext,
    SplitChange,
    SplitHistory,
    parse_flag_state,
    parse_variants,
)

LAUNCHED_AT = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
FIRST_CHANGE_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)
FIRST_CHANGE = "September 12, 2026 at 3:04 PM CEST"
SECOND_CHANGE = "September 12, 2026 at 3:21 PM CEST"
THIRD_CHANGE = "September 12, 2026 at 3:38 PM CEST"
MIXED_ASSIGNMENTS = "A sample ratio mismatch or users in more than one variant can come from this change."

EVERYONE = [{"properties": [], "rollout_percentage": 100}]
TARGETED = [{"properties": [{"key": "plan", "value": "pro", "type": "person"}], "rollout_percentage": 100}]

RUNNING = {"is_launched": True, "is_running": True, "has_ended": False}
ENDED = {"is_launched": True, "is_running": False, "has_ended": True}


def _split(*variants: tuple[str, float]) -> list[dict[str, Any]]:
    return [{"key": key, "rollout_percentage": share} for key, share in variants]


EVEN = _split(("control", 50), ("test", 50))
UNEVEN = _split(("control", 80), ("test", 20))
THREE_WAY = _split(("control", 34), ("test", 33), ("blue", 33))
BLUE_ZEROED = _split(("control", 50), ("test", 50), ("blue", 0))
SHIPPED = _split(("control", 0), ("test", 100))


def _context(
    *splits: list[dict[str, Any]],
    status: dict[str, bool] = RUNNING,
    groups: list[dict[str, Any]] = EVERYONE,
    exposed_before_first: bool | None = True,
    exposed_between: bool | None = None,
    launched_at: datetime = LAUNCHED_AT,
    archived: bool = False,
    deleted: bool = False,
) -> HealthContext:
    changes = tuple(
        SplitChange(
            changed_at=FIRST_CHANGE_AT + timedelta(minutes=17 * index),
            before=parse_variants(before),
            after=parse_variants(after),
        )
        for index, (before, after) in enumerate(zip(splits, splits[1:]))
    )
    return HealthContext(
        **status,
        is_paused=False,
        archived=archived,
        flag=parse_flag_state(active=True, deleted=deleted, groups=groups, variants=splits[-1]),
        baseline_variant_key=None,
        primary_metric_count=1,
        secondary_metric_count=0,
        exposures=None,
        split_history=SplitHistory(
            launched_at=launched_at,
            team_timezone="Europe/Berlin",
            counted_changes=changes,
            exposed_before_first=exposed_before_first,
            exposed_between=exposed_between,
        ),
    )


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
                f'Variant "test" was rolled out to 100% of the people the flag targets on {FIRST_CHANGE}, while the '
                'experiment is still running. Since then, everyone the flag targets gets variant "test". '
                f"End the experiment with a conclusion, or restore the split. {MIXED_ASSIGNMENTS}",
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

        assert finding is not None
        self.assertEqual(finding.code, ExperimentHealthFindingCode.SPLIT_CHANGED_MID_RUN)
        self.assertEqual((finding.subcode, finding.severity, finding.diagnostic_ref), expected)
        self.assertEqual(finding.detail, expected_detail)
        self.assertEqual(finding.actions, (ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,))

    def test_evidence_of_an_unknown_exposure(self) -> None:
        finding = split_changed_mid_run(_context(EVEN, UNEVEN, exposed_before_first=None))

        assert finding is not None
        self.assertEqual(
            finding.evidence,
            {
                "change_count": 1,
                "first_changed_at": "2026-09-12T13:04:00+00:00",
                "last_changed_at": "2026-09-12T13:04:00+00:00",
                "from": "control 50% / test 50%",
                "to": "control 80% / test 20%",
                "exposed_before_change": None,
                "seconds_after_launch": 11040,
            },
        )

    @parameterized.expand(
        [
            ("ended", _context(EVEN, UNEVEN, status=ENDED)),
            ("archived", _context(EVEN, UNEVEN, archived=True)),
            ("deleted_flag", _context(EVEN, UNEVEN, deleted=True)),
            ("nobody_exposed_before_any_change", _context(EVEN)),
            ("flag_without_variants_reported_by_flag_variants_mismatch", _context(EVEN, [])),
        ]
    )
    def test_no_finding(self, _name: str, ctx: HealthContext) -> None:
        self.assertIsNone(split_changed_mid_run(ctx))

    def test_shipped_finding_reports_a_rollout_to_everyone(self) -> None:
        ctx = _context(EVEN, SHIPPED, groups=EVERYONE)

        shipped = flag_state(ctx)

        self.assertIsNone(split_changed_mid_run(ctx))
        assert shipped is not None
        self.assertEqual(shipped.code, ExperimentHealthFindingCode.VARIANT_SHIPPED_WHILE_RUNNING)
        self.assertEqual(
            shipped.detail,
            f'Variant "test" is rolled out to 100% of users. It has been at 100% since {FIRST_CHANGE}, and the '
            "split was control 50% / test 50% before. The experiment is not comparing variants. End the experiment "
            "with a conclusion, or adjust the variant distribution of the linked feature flag to resume proper A/B "
            "testing.",
        )
