from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFinding,
    ExperimentHealthFindingActionKind,
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
)
from products.experiments.backend.health.checks.bucketing_changed import bucketing_changed_mid_run
from products.experiments.backend.health.context import FlagHistoryNotCheckedReason, HealthContext, parse_flag_state
from products.experiments.backend.health.skips import (
    NEEDS_VARIANTS,
    NOT_AFTER_END,
    CheckSkip,
    not_applicable,
    not_checked,
)
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT, flag_history
from products.feature_flags.backend.facade.edits import BucketingChange, BucketingSetting

LAUNCHED_AT = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
FIRST_CHANGE_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)
FIRST_CHANGE = "September 12, 2026 at 3:04 PM CEST"
SECOND_CHANGE = "September 12, 2026 at 3:21 PM CEST"
MIXED_ASSIGNMENTS = "A sample ratio mismatch or users in more than one variant can come from this change."
EVEN = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
KEY = BucketingSetting.KEY
AGGREGATION = BucketingSetting.AGGREGATION
IDENTIFIER = BucketingSetting.BUCKETING_IDENTIFIER
CONTINUITY = BucketingSetting.EXPERIENCE_CONTINUITY

Value = str | int | bool | None


def _context(
    *changes: tuple[BucketingSetting, Value, Value],
    first_change_at: datetime = FIRST_CHANGE_AT,
    exposed_before_first: bool | None = True,
    exposed_between: bool | None = None,
    is_running: bool = True,
    variants: list[dict[str, Any]] = EVEN,
    not_checked: FlagHistoryNotCheckedReason | None = None,
    exposed_units: int | None = None,
) -> HealthContext:
    bucketing = [
        BucketingChange(
            changed_at=first_change_at + timedelta(minutes=17 * index), setting=setting, before=before, after=after
        )
        for index, (setting, before, after) in enumerate(changes)
    ]
    return replace(
        RUNNING_CONTEXT,
        is_running=is_running,
        has_ended=not is_running,
        flag=parse_flag_state(
            active=True, deleted=False, groups=[{"properties": [], "rollout_percentage": 100}], variants=variants
        ),
        flag_history=flag_history(
            bucketing,
            launched_at=LAUNCHED_AT,
            exposed_before_first=exposed_before_first,
            exposed_between={ExperimentHealthFlagChangeKind.BUCKETING: exposed_between},
            not_checked=not_checked,
            exposed_units_before_last={ExperimentHealthFlagChangeKind.BUCKETING: exposed_units},
        ),
    )


class TestBucketingChangedMidRun(TestCase):
    @parameterized.expand(
        [
            (
                "key_changed",
                _context((KEY, "old-key", "new-key")),
                ("key_changed", ExperimentHealthFindingSeverity.WARNING, "The flag key changed after launch"),
                f'The flag key changed from "old-key" to "new-key" on {FIRST_CHANGE}. The key is an input of the '
                'variant draw, so every user got a new one. Exposures under "old-key" are no longer in the results, '
                'and code that still uses "old-key" no longer gets this flag. Reset the experiment, or move its start '
                f"date to {FIRST_CHANGE}.",
            ),
            (
                "key_changed_before_4_people",
                _context((KEY, "old-key", "new-key"), exposed_units=4),
                ("key_changed", ExperimentHealthFindingSeverity.INFO, "The flag key changed after launch"),
                f'The flag key changed from "old-key" to "new-key" on {FIRST_CHANGE}. The change came 3 hours after '
                f"launch, when 4 people had been exposed. Move the start date to {FIRST_CHANGE} so the results count only exposures after it. "
                'Code that still uses "old-key" no longer gets this flag.',
            ),
            (
                "key_changed_before_5_people",
                _context((KEY, "old-key", "new-key"), exposed_units=5),
                ("key_changed", ExperimentHealthFindingSeverity.WARNING, "The flag key changed after launch"),
                f'The flag key changed from "old-key" to "new-key" on {FIRST_CHANGE}. The key is an input of the '
                'variant draw, so every user got a new one. Exposures under "old-key" are no longer in the results, '
                'and code that still uses "old-key" no longer gets this flag. Reset the experiment, or move its start '
                f"date to {FIRST_CHANGE}.",
            ),
            (
                "aggregation_changed_before_4_people",
                _context((AGGREGATION, None, 0), exposed_units=4),
                (
                    "aggregation_changed",
                    ExperimentHealthFindingSeverity.INFO,
                    "The flag's variant assignment changed after launch",
                ),
                f"The flag changed from matching by users to matching by groups on {FIRST_CHANGE}. The change came 3 "
                f"hours after launch, when 4 people had been exposed. Move the start date to {FIRST_CHANGE} so the results count only exposures after it.",
            ),
            (
                "bucketing_identifier_changed_days_after_launch",
                _context((IDENTIFIER, "distinct_id", "device_id"), first_change_at=FIRST_CHANGE_AT + timedelta(days=8)),
                (
                    "bucketing_identifier_changed",
                    ExperimentHealthFindingSeverity.WARNING,
                    "The flag's variant assignment changed after launch",
                ),
                "The flag changed from matching by user ID to matching by device ID on September 20, 2026 at 3:04 PM "
                "CEST. The change came 8 days after launch. Users whose device ID differs from their user ID got a "
                f"new variant draw, so they may have switched variants. {MIXED_ASSIGNMENTS} Reset the experiment, or "
                "move its start date to September 20, 2026 at 3:04 PM CEST.",
            ),
            (
                "experience_continuity_changed_with_unknown_exposure",
                _context((CONTINUITY, True, False), exposed_before_first=None),
                (
                    "experience_continuity_changed",
                    ExperimentHealthFindingSeverity.WARNING,
                    "The flag's variant assignment changed after launch",
                ),
                f'"Persist flag across authentication steps" was turned off on {FIRST_CHANGE}. The change came 3 '
                "hours after launch. Users who logged in got a new variant draw, so they may have switched variants. "
                f"{MIXED_ASSIGNMENTS} Reset the experiment, or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "aggregation_changed",
                _context((AGGREGATION, None, 0)),
                (
                    "aggregation_changed",
                    ExperimentHealthFindingSeverity.WARNING,
                    "The flag's variant assignment changed after launch",
                ),
                f"The flag changed from matching by users to matching by groups on {FIRST_CHANGE}. Every user and "
                "group got a new variant draw, so people exposed before the change may have switched variants. "
                f"{MIXED_ASSIGNMENTS} Reset the experiment, or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "two_settings_name_the_key_first",
                _context((CONTINUITY, True, False), (KEY, "old-key", "new-key")),
                ("key_changed", ExperimentHealthFindingSeverity.WARNING, "The flag key changed after launch"),
                f'The flag key changed from "old-key" to "new-key" on {SECOND_CHANGE}. "Persist flag across '
                f'authentication steps" was turned off on {FIRST_CHANGE}. The key is an input of the variant draw, so '
                'every user got a new one. Exposures under "old-key" are no longer in the results, and code that '
                'still uses "old-key" no longer gets this flag. Reset the experiment, or move its start date to '
                f"{SECOND_CHANGE}.",
            ),
            (
                "set_back_with_exposures_in_between",
                _context(
                    (IDENTIFIER, "distinct_id", "device_id"),
                    (IDENTIFIER, "device_id", "distinct_id"),
                    exposed_between=True,
                ),
                (
                    "reverted",
                    ExperimentHealthFindingSeverity.WARNING,
                    "The flag's variant assignment changed after launch",
                ),
                f'The flag\'s "Match by" setting changed on {FIRST_CHANGE} and was set back on {SECOND_CHANGE}. '
                "People exposed in between got a new variant draw, so they may have switched variants. Move the "
                f"start date to {SECOND_CHANGE}, or reset the experiment.",
            ),
            (
                "set_back_before_4_people",
                _context(
                    (IDENTIFIER, "distinct_id", "device_id"),
                    (IDENTIFIER, "device_id", "distinct_id"),
                    exposed_between=True,
                    exposed_units=4,
                ),
                (
                    "reverted",
                    ExperimentHealthFindingSeverity.INFO,
                    "The flag's variant assignment changed after launch",
                ),
                f'The flag\'s "Match by" setting changed on {FIRST_CHANGE} and was set back on {SECOND_CHANGE}. '
                "The last change came 3 hours after launch, when 4 people had been exposed. Move the start date to "
                f"{SECOND_CHANGE} so the results count only exposures after it.",
            ),
            (
                "set_back_with_nobody_in_between",
                _context((KEY, "old-key", "new-key"), (KEY, "new-key", "old-key"), exposed_between=False),
                (
                    "reverted",
                    ExperimentHealthFindingSeverity.INFO,
                    "The flag's variant assignment changed and was set back",
                ),
                f"The flag key changed on {FIRST_CHANGE} and was set back 17 minutes later. Nobody was exposed in "
                "between.",
            ),
            (
                "not_checked",
                _context((KEY, "old-key", "new-key"), not_checked=FlagHistoryNotCheckedReason.EXPOSURE_FILTERS),
                ("not_checked", ExperimentHealthFindingSeverity.INFO, "Variant assignment changes were not checked"),
                f'The flag key changed from "old-key" to "new-key" on {FIRST_CHANGE}. This check can\'t tell whether '
                "anyone was exposed before the change, because the exposure criteria filter by properties. Review "
                "the change in the flag history.",
            ),
        ]
    )
    def test_reports_bucketing_changes(
        self,
        _name: str,
        ctx: HealthContext,
        expected: tuple[str, ExperimentHealthFindingSeverity, str],
        expected_detail: str,
    ) -> None:
        finding = bucketing_changed_mid_run(ctx)

        assert isinstance(finding, ExperimentHealthFinding)
        self.assertEqual(finding.code, ExperimentHealthFindingCode.BUCKETING_CHANGED_MID_RUN)
        self.assertEqual((finding.subcode, finding.severity, finding.title), expected)
        self.assertEqual(finding.detail, expected_detail)
        self.assertEqual(finding.actions, (ExperimentHealthFindingActionKind.OPEN_FEATURE_FLAG_HISTORY,))

    @parameterized.expand(
        [
            ("no_change", _context(), None),
            ("ended", _context((KEY, "old-key", "new-key"), is_running=False), not_applicable(NOT_AFTER_END)),
            (
                "flag_without_variants",
                _context((KEY, "old-key", "new-key"), variants=[]),
                not_applicable(NEEDS_VARIANTS),
            ),
            # The split check reports a history the reader can't view.
            (
                "no_history_access",
                _context(not_checked=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS),
                not_checked("Couldn't check because you can't view the linked feature flag's history"),
            ),
        ]
    )
    def test_reports_nothing(self, _name: str, ctx: HealthContext, expected: CheckSkip | None) -> None:
        self.assertEqual(bucketing_changed_mid_run(ctx), expected)
