from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFindingCode,
    ExperimentHealthFindingSeverity,
    ExperimentHealthFlagChangeKind,
)
from products.experiments.backend.health.checks.conditions_changed import release_conditions_changed_mid_run
from products.experiments.backend.health.condition_changes import parse_release_conditions
from products.experiments.backend.health.context import (
    ChangeWindow,
    ConditionsChange,
    ConditionSetTraffic,
    FlagHistoryNotCheckedReason,
    HealthContext,
    parse_flag_state,
)
from products.experiments.backend.health.test.factories import RUNNING_CONTEXT, flag_history

LAUNCHED_AT = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
FIRST_CHANGE_AT = datetime(2026, 9, 12, 13, 4, tzinfo=UTC)
FIRST_CHANGE = "September 12, 2026 at 3:04 PM CEST"
SECOND_CHANGE = "September 12, 2026 at 3:21 PM CEST"
THIRD_CHANGE = "September 12, 2026 at 3:38 PM CEST"
EVEN = [{"key": "control", "rollout_percentage": 50}, {"key": "test", "rollout_percentage": 50}]
WITH_HOLDOUT = [*EVEN, {"key": "holdout", "rollout_percentage": 0}]
PRO = {"properties": [{"key": "plan", "value": ["pro"], "operator": "exact", "type": "person"}]}
EVERYONE: dict[str, Any] = {"properties": []}
PRO_PINNED = {**PRO, "variant": "test"}
PRO_OR_TEAM_PINNED = {
    "properties": [{"key": "plan", "value": ["pro", "team"], "operator": "exact", "type": "person"}],
    "variant": "test",
}
TEAM = {"properties": [{"key": "plan", "value": ["team"], "operator": "exact", "type": "person"}]}
EU = {"properties": [{"key": "$geoip_continent_code", "value": ["EU"], "operator": "exact", "type": "person"}]}
EU_CONTROL = {
    "properties": [{"key": "$geoip_continent_code", "value": ["EU"], "operator": "exact", "type": "person"}],
    "variant": "control",
}
TRAFFIC_SINCE = "September 13, 2026 at 10:00 AM CEST"


def _context(
    *conditions: list[dict[str, Any]],
    exposed_between: bool | None = None,
    not_checked: FlagHistoryNotCheckedReason | None = None,
    people_by_set: dict[int, int] | None = None,
    now: list[dict[str, Any]] | None = None,
    exposed_during_overrides: dict[ChangeWindow, bool | None] | None = None,
    variants: list[dict[str, Any]] = EVEN,
    exposed_units: int | None = None,
) -> HealthContext:
    variant_keys = [variant["key"] for variant in variants]
    changes = [
        ConditionsChange(
            changed_at=FIRST_CHANGE_AT + timedelta(minutes=17 * index),
            before=parse_release_conditions(before, variant_keys=variant_keys),
            after=parse_release_conditions(after, variant_keys=variant_keys),
        )
        for index, (before, after) in enumerate(zip(conditions, conditions[1:]))
    ]
    return replace(
        RUNNING_CONTEXT,
        flag=parse_flag_state(active=True, deleted=False, groups=now or conditions[-1], variants=variants),
        flag_history=flag_history(
            changes,
            launched_at=LAUNCHED_AT,
            exposed_between={ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS: exposed_between},
            not_checked=not_checked,
            release_conditions=None if now is None else parse_release_conditions(now, variant_keys=variant_keys),
            exposed_during_overrides=exposed_during_overrides,
            exposed_units_before_last={ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS: exposed_units},
        ),
        condition_set_traffic=None if people_by_set is None else _traffic(people_by_set),
    )


def _traffic(people_by_set: dict[int, int]) -> ConditionSetTraffic:
    calls = 2 * sum(people_by_set.values())
    return ConditionSetTraffic(
        since=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
        team_timezone="Europe/Berlin",
        people_by_set=people_by_set,
        calls=calls,
        remotely_evaluated_calls=calls,
        people_assigned_outside=0,
    )


INFO = ExperimentHealthFindingSeverity.INFO
WARNING = ExperimentHealthFindingSeverity.WARNING
CHANGED_TITLE = "The release conditions changed after launch"
OVERRIDE_TITLE = "A variant override was removed after launch"
REORDERED_TITLE = "The order of the release conditions changed after launch"
OVERRIDE_MOVED = (
    'Users it matched got "test" while the override was in place and a random variant after, so those exposed while '
    'it was in place may have switched variants. Their exposures under "test" stay in the results.'
)


class TestReleaseConditionsChangedMidRun(TestCase):
    @parameterized.expand(
        [
            (
                "condition_added",
                _context([PRO], [PRO, EVERYONE]),
                ("conditions_changed", INFO, CHANGED_TITLE, "A6"),
                f"The release conditions changed on {FIRST_CHANGE}, from 1 condition to 2 conditions. People who match "
                "differently now enter or leave the experiment, and people exposed before the change stay in the "
                "results. Review the change in the flag history.",
            ),
            (
                "criteria_changed_twice",
                _context([PRO], [EVERYONE], [{"properties": [{"key": "plan", "value": ["team"], "type": "person"}]}]),
                ("conditions_changed", INFO, CHANGED_TITLE, "A6"),
                f"The release conditions changed 2 times between {FIRST_CHANGE} and {SECOND_CHANGE}. People who "
                "match differently now enter or leave the experiment, and people exposed before the changes stay in "
                "the results. Review the changes in the flag history.",
            ),
            (
                "override_removed_from_a_large_share",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE], people_by_set={1: 300, 2: 2700}),
                ("variant_override_changed", WARNING, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} Since '
                f'{TRAFFIC_SINCE}, Set 1 matched about 18.2% of the users who would get "test" with the override in '
                f"place (300 of about 1,650). Reset the experiment, or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "override_removed_from_a_large_share_before_4_people",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE], people_by_set={1: 300, 2: 2700}, exposed_units=4),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. The change came 3 hours after '
                f"launch, when 4 people had been exposed. Move the start date to {FIRST_CHANGE} so the results count only exposures after it. "
                f'Since {TRAFFIC_SINCE}, Set 1 matched about 18.2% of the users who would get "test" with the '
                "override in place (300 of about 1,650).",
            ),
            (
                "override_removed_from_a_large_share_before_5_people",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE], people_by_set={1: 300, 2: 2700}, exposed_units=5),
                ("variant_override_changed", WARNING, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} Since '
                f'{TRAFFIC_SINCE}, Set 1 matched about 18.2% of the users who would get "test" with the override in '
                f"place (300 of about 1,650). Reset the experiment, or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "override_removed_without_a_measurement_before_4_people",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE], exposed_units=4),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} PostHog '
                "can't measure how many users Set 1 matches. Reset the experiment, or move its start date to "
                f"{FIRST_CHANGE}.",
            ),
            (
                "override_removed_from_a_few_percent",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE], people_by_set={1: 30, 2: 2970}),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                None,
            ),
            (
                "override_removed_with_too_few_people",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE], people_by_set={1: 10, 2: 50}),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} Too few '
                f"users called the flag since {TRAFFIC_SINCE} to measure how many users Set 1 matches. Reset the "
                f"experiment, or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "override_removed_without_a_measurement",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE]),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} PostHog '
                "can't measure how many users Set 1 matches. Reset the experiment, or move its start date to "
                f"{FIRST_CHANGE}.",
            ),
            (
                "override_changed_then_removed",
                _context(
                    [PRO_PINNED, EVERYONE],
                    [{**PRO, "variant": "control"}, EVERYONE],
                    [PRO, EVERYONE],
                    people_by_set={1: 300, 2: 2700},
                ),
                ("variant_override_changed", WARNING, OVERRIDE_TITLE, "A7"),
                f'The variant override "control" of Set 1 was set on {FIRST_CHANGE} and removed on {SECOND_CHANGE}. '
                'Users it matched got "control" while the override was in place and a random variant after, so '
                'those exposed while it was in place may have switched variants. Their exposures under "control" '
                f"stay in the results. Since {TRAFFIC_SINCE}, Set 1 matched about 18.2% of the users who would get "
                f'"control" with the override in place (300 of about 1,650). Reset the experiment, or move its start '
                f"date to {SECOND_CHANGE}.",
            ),
            (
                "override_removed_set_back_and_removed_again",
                _context(
                    [PRO_PINNED, EVERYONE],
                    [PRO, EVERYONE],
                    [PRO_PINNED, EVERYONE],
                    [PRO, EVERYONE],
                    people_by_set={1: 300, 2: 2700},
                    exposed_during_overrides={
                        ChangeWindow(
                            start=FIRST_CHANGE_AT + timedelta(minutes=17), end=FIRST_CHANGE_AT + timedelta(minutes=34)
                        ): False
                    },
                ),
                ("variant_override_changed", WARNING, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {THIRD_CHANGE}. {OVERRIDE_MOVED} Since '
                f'{TRAFFIC_SINCE}, Set 1 matched about 18.2% of the users who would get "test" with the override in '
                f"place (300 of about 1,650). Reset the experiment, or move its start date to {THIRD_CHANGE}.",
            ),
            (
                "override_removed_with_its_rollout_set_to_zero",
                _context([PRO_PINNED, EVERYONE], [{**PRO, "rollout_percentage": 0}, EVERYONE], people_by_set={2: 3000}),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} PostHog '
                f"can't measure how many users the override matched. Reset the experiment, or move its start date to "
                f"{FIRST_CHANGE}.",
            ),
            (
                "overrides_removed_from_a_small_share_and_a_variant_at_zero_percent",
                _context(
                    [PRO_PINNED, {**TEAM, "variant": "holdout"}, EVERYONE],
                    [PRO, TEAM, EVERYONE],
                    people_by_set={1: 10, 2: 5, 3: 2985},
                    variants=WITH_HOLDOUT,
                ),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                None,
            ),
            (
                "override_removed_with_its_condition_next_to_a_small_share",
                _context(
                    [PRO_PINNED, {**TEAM, "variant": "test"}, EVERYONE],
                    [TEAM, EVERYONE],
                    people_by_set={1: 10, 2: 2990},
                ),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'A release condition with the variant override "test" was removed on {FIRST_CHANGE}. The variant '
                f'override "test" of Set 1 was removed on {FIRST_CHANGE}. Users they matched got the override\'s '
                "variant while it was in place and a random variant after, so those exposed while it was in place "
                "may have switched variants. Their exposures stay in the results. PostHog can't measure how many "
                f"users these conditions match. Reset the experiment, or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "override_removed_with_its_condition",
                _context([PRO_PINNED, EVERYONE], [EVERYONE]),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'A release condition with the variant override "test" was removed on {FIRST_CHANGE}. '
                f"{OVERRIDE_MOVED} PostHog can't measure how many users the override matched. Reset the experiment, "
                f"or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "override_set_and_removed_again",
                _context(
                    [PRO, EVERYONE],
                    [PRO_PINNED, EVERYONE],
                    [PRO, EVERYONE],
                    exposed_between=True,
                    people_by_set={1: 300, 2: 2700},
                ),
                ("reverted", WARNING, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was set on {FIRST_CHANGE} and removed on {SECOND_CHANGE}. '
                f'{OVERRIDE_MOVED} Since {TRAFFIC_SINCE}, Set 1 matched about 18.2% of the users who would get "test" '
                "with the override in place (300 of about 1,650). Reset the experiment, or move its start date to "
                f"{SECOND_CHANGE}.",
            ),
            (
                "override_removed_before_a_reorder_that_is_no_change",
                _context(
                    [PRO_PINNED, EU, EVERYONE],
                    [PRO, EU, EVERYONE],
                    now=[EU, PRO, EVERYONE],
                    people_by_set={1: 30, 2: 300, 3: 2670},
                ),
                ("variant_override_changed", WARNING, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 2 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} Since '
                f'{TRAFFIC_SINCE}, Set 2 matched about 18.2% of the users who would get "test" with the override in '
                f"place (300 of about 1,650). Reset the experiment, or move its start date to {FIRST_CHANGE}.",
            ),
            (
                "override_removed_with_its_filters_edited",
                _context([PRO_PINNED, EVERYONE], [TEAM, EVERYONE], people_by_set={2: 3000}),
                ("variant_override_changed", INFO, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 was removed on {FIRST_CHANGE}. {OVERRIDE_MOVED} PostHog '
                f"can't measure how many users the override matched. Reset the experiment, or move its start date to "
                f"{FIRST_CHANGE}.",
            ),
            (
                "override_removed_and_set_back",
                _context(
                    [PRO_PINNED, EVERYONE],
                    [PRO, EVERYONE],
                    [PRO_PINNED, EVERYONE],
                    exposed_between=True,
                    people_by_set={1: 300, 2: 2700},
                ),
                ("reverted", WARNING, OVERRIDE_TITLE, "A7"),
                f'The variant override "test" of Set 1 changed on {FIRST_CHANGE} and was set back on {SECOND_CHANGE}. '
                'Between these changes, users it matches did not get "test", so those exposed then may have '
                f"switched variants. Their exposures stay in the results. Since {TRAFFIC_SINCE}, Set 1 matched about "
                '18.2% of the users who would get "test" with the override in place (300 of about 1,650). Reset the '
                f"experiment, or move its start date to {SECOND_CHANGE}.",
            ),
            (
                "pinned_conditions_reordered",
                _context([PRO_PINNED, EU_CONTROL, EVERYONE], [EU_CONTROL, PRO_PINNED, EVERYONE]),
                ("variant_override_changed", INFO, REORDERED_TITLE, "A7"),
                f"The release conditions changed on {FIRST_CHANGE}, and conditions that serve different variants now "
                "come in another order. Users who match more than one of them now get the variant of another "
                "condition, so those exposed before the change may have switched variants. Their exposures stay in "
                "the results. Review the change in the flag history.",
            ),
            (
                "override_in_place_only_while_nobody_was_exposed",
                _context(
                    [PRO, EVERYONE],
                    [PRO_PINNED, EVERYONE],
                    [PRO, EVERYONE],
                    [PRO, EVERYONE, EU],
                    people_by_set={1: 300, 2: 2700},
                    exposed_during_overrides={
                        ChangeWindow(start=FIRST_CHANGE_AT, end=FIRST_CHANGE_AT + timedelta(minutes=17)): False
                    },
                ),
                ("conditions_changed", INFO, CHANGED_TITLE, "A6"),
                f"The release conditions changed 3 times between {FIRST_CHANGE} and {THIRD_CHANGE}, from 2 conditions "
                "to 3 conditions. People who match differently now enter or leave the experiment, and people exposed "
                "before the changes stay in the results. Review the changes in the flag history.",
            ),
            (
                "filters_of_a_pinned_condition_edited",
                _context([PRO_PINNED, EVERYONE], [PRO_OR_TEAM_PINNED, EVERYONE]),
                ("conditions_changed", INFO, CHANGED_TITLE, "A6"),
                f"The release conditions changed on {FIRST_CHANGE}. People who match differently now enter or leave "
                "the experiment, and people exposed before the change stay in the results. Set 1 has the variant "
                'override "test", so users who now match it or no longer match it may also have switched variants. '
                "Review the change in the flag history.",
            ),
            (
                "set_back_with_exposures_in_between",
                _context([PRO], [EVERYONE], [PRO], exposed_between=True),
                ("reverted", INFO, "The release conditions changed and were set back", "A6"),
                f"The release conditions changed on {FIRST_CHANGE} and were set back on {SECOND_CHANGE}. People "
                "exposed in between were targeted by other conditions, and they stay in the results. Review the "
                "changes in the flag history.",
            ),
            (
                "not_checked",
                _context([PRO], [EVERYONE], not_checked=FlagHistoryNotCheckedReason.NO_QUERY_ACCESS),
                ("not_checked", INFO, "Release condition changes were not checked", "A6"),
                f"The release conditions changed on {FIRST_CHANGE}. This check can't tell whether anyone was exposed "
                "before the change, because this API key can't query events. Add the query:read scope to this API "
                "key, or review the change in the flag history.",
            ),
        ]
    )
    def test_reports_release_condition_changes(
        self,
        _name: str,
        ctx: HealthContext,
        expected: tuple[str, ExperimentHealthFindingSeverity, str, str],
        expected_detail: str | None,
    ) -> None:
        finding = release_conditions_changed_mid_run(ctx)

        assert finding is not None
        self.assertEqual(finding.code, ExperimentHealthFindingCode.RELEASE_CONDITIONS_CHANGED_MID_RUN)
        self.assertEqual((finding.subcode, finding.severity, finding.title, finding.diagnostic_ref), expected)
        if expected_detail is not None:
            self.assertEqual(finding.detail, expected_detail)

    @parameterized.expand(
        [
            ("no_change", _context([PRO])),
            ("set_back_with_nobody_in_between", _context([PRO], [EVERYONE], [PRO], exposed_between=False)),
            ("no_history_access", _context([PRO], not_checked=FlagHistoryNotCheckedReason.NO_HISTORY_ACCESS)),
            # The forced-variant check reports an override in place, with the time it was set.
            ("override_added", _context([PRO, EVERYONE], [PRO_PINNED, EVERYONE])),
            ("pinned_condition_added", _context([EVERYONE], [PRO_PINNED, EVERYONE])),
            (
                "override_changed_to_another_variant",
                _context([PRO_PINNED, EVERYONE], [{**PRO, "variant": "control"}, EVERYONE]),
            ),
            (
                "override_removed_from_under_one_percent",
                _context([PRO_PINNED, EVERYONE], [PRO, EVERYONE], people_by_set={1: 10, 2: 2990}),
            ),
        ]
    )
    def test_reports_nothing(self, _name: str, ctx: HealthContext) -> None:
        self.assertIsNone(release_conditions_changed_mid_run(ctx))
