import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.conf import settings

from parameterized import parameterized

from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.test.persons import create_group_type_mapping, create_person

from products.error_tracking.backend.facade.testing import (
    create_issue,
    create_issue_fingerprint,
    sync_issue_to_clickhouse,
)
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.flag_windows import query as flag_window_query
from products.feature_flags.backend.flag_windows.errors import (
    ConditionErrors,
    ErrorCounts,
    ErrorsByLastValue,
    errors_by_bucket,
)
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedCondition, WatchedEdit
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

EDITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
WINDOW = timedelta(minutes=30)

BOOLEAN = WatchedEdit(
    id="boolean", flag_key="new-checkout", edited_at=EDITED_AT, group_type_index=None, variants=(), enables=False
)
MULTIVARIATE = WatchedEdit(
    id="multivariate",
    flag_key="pricing-test",
    edited_at=EDITED_AT,
    group_type_index=None,
    variants=("control", "test"),
    enables=False,
)
ENABLED = WatchedEdit(
    id="enabled", flag_key="new-checkout", edited_at=EDITED_AT, group_type_index=None, variants=(), enables=True
)

# (distinct id, event, minutes after the edit, event properties)
Event = tuple[str, str, int, dict[str, Any]]


class TestErrorsByBucket(ClickhouseTestMixin, BaseTest):
    def _send(self, events: list[Event], plans: dict[str, str] | None = None) -> None:
        plans = plans or {}
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, _, _, _ in events):
            create_person(
                team=self.team,
                distinct_ids=[distinct_id],
                properties={"plan": plans[distinct_id]} if distinct_id in plans else {},
            )
        for distinct_id, event, minutes, properties in events:
            _create_event(
                team=self.team,
                event=event,
                distinct_id=distinct_id,
                timestamp=EDITED_AT + timedelta(minutes=minutes),
                properties=properties,
            )
        flush_persons_and_events()

    def _since_edit(self, edit: WatchedEdit) -> ErrorCounts:
        errors = errors_by_bucket(self.team, [edit], EDITED_AT, EDITED_AT + WINDOW, WINDOW)
        [bucket] = errors[edit.id]
        return bucket.since_edit

    @parameterized.expand(
        [
            (
                "error_events_split_by_the_flag_value_they_carry",
                BOOLEAN,
                [
                    ("person-1", "$exception", 1, {"$feature/new-checkout": True}),
                    ("person-1", "$exception", 2, {"$feature/new-checkout": True}),
                    ("person-2", "$exception", 3, {"$feature/new-checkout": False}),
                    # A server error without the flag counts only among all errors.
                    ("person-3", "$exception", 4, {}),
                    ("person-4", "$pageview", 5, {"$feature/new-checkout": True}),
                    # Errors before the edit belong to the old value.
                    ("person-5", "$exception", -5, {"$feature/new-checkout": True}),
                ],
                ErrorCounts(
                    with_errors=3,
                    with_new_errors=0,
                    exposed_with_errors=1,
                    unexposed_with_errors=1,
                    by_variant={},
                    by_last_value=ErrorsByLastValue(exposed_with_errors=1, unexposed_with_errors=1),
                ),
            ),
            (
                "multivariate_errors_count_per_variant",
                MULTIVARIATE,
                [
                    ("person-1", "$exception", 1, {"$feature/pricing-test": "control"}),
                    ("person-2", "$exception", 2, {"$feature/pricing-test": "test"}),
                    ("person-3", "$exception", 3, {"$feature/pricing-test": False}),
                ],
                ErrorCounts(
                    with_errors=3,
                    with_new_errors=0,
                    exposed_with_errors=2,
                    unexposed_with_errors=1,
                    by_variant={"control": 1, "test": 1},
                    by_last_value=ErrorsByLastValue(exposed_with_errors=2, unexposed_with_errors=1),
                ),
            ),
            (
                "enabling_edit_counts_errors_of_apps_that_loaded_flags_without_it_as_unexposed",
                ENABLED,
                [
                    ("person-1", "$exception", 1, {"$feature/new-checkout": True}),
                    (
                        "person-2",
                        "$exception",
                        2,
                        {"$active_feature_flags": ["other-flag"], "$feature/other-flag": True},
                    ),
                ],
                ErrorCounts(
                    with_errors=2,
                    with_new_errors=0,
                    exposed_with_errors=1,
                    unexposed_with_errors=1,
                    by_variant={},
                    by_last_value=ErrorsByLastValue(exposed_with_errors=1, unexposed_with_errors=1),
                ),
            ),
        ]
    )
    def test_errors_since_the_edit(
        self, _name: str, edit: WatchedEdit, events: list[Event], expected: ErrorCounts
    ) -> None:
        self._send(events)

        self.assertEqual(self._since_edit(edit), expected)

    def test_an_error_is_new_only_when_its_issue_was_first_seen_after_that_edit(self) -> None:
        issue_id = create_issue(team_id=self.team.pk, name="TypeError")
        create_issue_fingerprint(
            team_id=self.team.pk, issue_id=issue_id, fingerprint="old", first_seen=EDITED_AT - timedelta(days=3)
        )
        # An old issue can gain a fingerprint after the edit, for example by a merge.
        create_issue_fingerprint(
            team_id=self.team.pk, issue_id=issue_id, fingerprint="added", first_seen=EDITED_AT + timedelta(minutes=1)
        )
        sync_issue_to_clickhouse(team_id=self.team.pk, issue_id=issue_id)
        self._send(
            [
                ("person-1", "$exception", 1, {"$exception_fingerprint": "old"}),
                ("person-2", "$exception", 2, {"$exception_fingerprint": "added"}),
                # A fingerprint that error tracking hasn't synced yet is new.
                ("person-3", "$exception", 3, {"$exception_fingerprint": "unsynced"}),
                # An exception that error tracking couldn't fingerprint has no issue to be new.
                ("person-4", "$exception", 4, {}),
            ]
        )

        # The issue is old for BOOLEAN and new for an edit before its first fingerprint, in the same query.
        earlier = WatchedEdit(
            id="earlier",
            flag_key="new-checkout",
            edited_at=EDITED_AT - timedelta(days=4),
            group_type_index=None,
            variants=(),
            enables=False,
        )
        errors = errors_by_bucket(self.team, [BOOLEAN, earlier], EDITED_AT, EDITED_AT + WINDOW, WINDOW)

        self.assertEqual(
            {edit_id: buckets[0].since_edit.with_new_errors for edit_id, buckets in errors.items()},
            {"boolean": 1, "earlier": 3},
        )

    def test_an_error_without_the_flag_takes_the_value_of_the_last_event_before_it(self) -> None:
        def called(flag_key: str, response: bool) -> dict[str, Any]:
            return {"$feature_flag": flag_key, "$feature_flag_response": response}

        # HogQL hides the group of an event sent before the group type existed.
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=EDITED_AT - timedelta(days=1),
        )
        self._send(
            [
                # The value on a pageview before the error.
                ("person-1", "$pageview", 1, {"$feature/new-checkout": True}),
                ("person-1", "$feature_flag_called", 2, called("other-flag", True)),
                ("person-1", "$exception", 3, {}),
                ("person-2", "$pageview", 1, {"$feature/new-checkout": False, "$feature/other-flag": False}),
                ("person-2", "$exception", 2, {}),
                # A value after the error doesn't count.
                ("person-3", "$exception", 2, {}),
                ("person-3", "$pageview", 4, {"$feature/new-checkout": True}),
                # The value of a flag call.
                ("person-4", "$feature_flag_called", 1, called("new-checkout", True)),
                ("person-4", "$exception", 2, {}),
                # A value from before the edit is the old value.
                ("person-5", "$pageview", -10, {"$feature/new-checkout": True}),
                ("person-5", "$exception", 2, {}),
                # The value on the error event wins over an earlier one.
                ("person-6", "$pageview", 1, {"$feature/new-checkout": True}),
                ("person-6", "$exception", 2, {"$feature/new-checkout": False}),
                # Only an unwatched flag, which reads as unexposed for an edit that enables the flag.
                ("person-7", "$pageview", 1, {"$active_feature_flags": ["unwatched"], "$feature/unwatched": True}),
                ("person-7", "$exception", 2, {}),
                # Another person of the same group gives the group's value.
                ("person-8", "$pageview", 1, {"$feature/org-beta": True, "$group_0": "org-a"}),
                ("person-9", "$exception", 2, {"$group_0": "org-a"}),
                # The latest of two values before the error wins.
                ("person-10", "$pageview", 1, {"$feature/new-checkout": True}),
                ("person-10", "$pageview", 2, {"$feature/new-checkout": False}),
                ("person-10", "$exception", 3, {}),
                # A later pageview wins over an earlier flag call.
                ("person-11", "$feature_flag_called", 1, called("new-checkout", True)),
                ("person-11", "$pageview", 2, {"$feature/new-checkout": False}),
                ("person-11", "$exception", 3, {}),
            ]
        )
        other = dataclasses.replace(BOOLEAN, id="other", flag_key="other-flag")
        group = dataclasses.replace(BOOLEAN, id="group", flag_key="org-beta", group_type_index=0)

        errors = errors_by_bucket(self.team, [BOOLEAN, other, ENABLED, group], EDITED_AT, EDITED_AT + WINDOW, WINDOW)

        self.assertEqual(
            {edit_id: bucket.since_edit.by_last_value for edit_id, [bucket] in errors.items()},
            {
                "boolean": ErrorsByLastValue(exposed_with_errors=2, unexposed_with_errors=4),
                "other": ErrorsByLastValue(exposed_with_errors=1, unexposed_with_errors=1),
                "enabled": ErrorsByLastValue(exposed_with_errors=2, unexposed_with_errors=5),
                "group": ErrorsByLastValue(exposed_with_errors=1, unexposed_with_errors=0),
            },
        )

    def test_a_last_value_counts_from_the_edit_and_within_the_lookback_before_the_range(self) -> None:
        self._send(
            [
                # After the earlier edit and within the lookback, but before the later edit.
                ("person-1", "$pageview", -10, {"$feature/new-checkout": True}),
                ("person-1", "$exception", 50, {}),
                # After the earlier edit, but before the lookback.
                ("person-2", "$pageview", -30, {"$feature/new-checkout": True}),
                ("person-2", "$exception", 50, {}),
                # After both edits and within the lookback.
                ("person-3", "$pageview", 10, {"$feature/new-checkout": True}),
                ("person-3", "$exception", 50, {}),
            ]
        )
        earlier = dataclasses.replace(BOOLEAN, id="earlier", edited_at=EDITED_AT - timedelta(minutes=90))
        start = EDITED_AT + timedelta(minutes=40)

        with patch.object(flag_window_query, "LAST_VALUE_LOOKBACK", timedelta(hours=1)):
            errors = errors_by_bucket(self.team, [earlier, BOOLEAN], start, start + WINDOW, WINDOW)

        self.assertEqual(
            {edit_id: bucket.since_edit.by_last_value for edit_id, [bucket] in errors.items()},
            {
                "earlier": ErrorsByLastValue(exposed_with_errors=2, unexposed_with_errors=0),
                "boolean": ErrorsByLastValue(exposed_with_errors=1, unexposed_with_errors=0),
            },
        )

    @parameterized.expand(
        [
            ("timeout", ClickHouseQueryTimeOut),
            ("memory", ClickHouseQueryMemoryLimitExceeded),
            ("estimated_too_slow", ClickHouseEstimatedQueryExecutionTimeTooLong),
        ]
    )
    def test_a_failed_last_value_query_keeps_the_other_counts(self, _name: str, error: type[Exception]) -> None:
        self._send([("person-1", "$exception", 1, {"$feature/new-checkout": True})])
        run_query = flag_window_query.execute_hogql_query

        def fail_last_values(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("query_type") == "flag_errors_by_last_value_by_bucket":
                raise error()
            return run_query(*args, **kwargs)

        with patch.object(flag_window_query, "execute_hogql_query", side_effect=fail_last_values):
            since_edit = self._since_edit(BOOLEAN)

        self.assertEqual((since_edit.exposed_with_errors, since_edit.by_last_value), (1, None))

    @parameterized.expand(
        [
            (f"{mode_name}_{response_name}", mode, in_flag_evaluations, response, expected)
            for mode_name, mode, in_flag_evaluations in (
                ("read_flag_evaluations", FlagEvaluationsMode.READ_FLAG_EVALUATIONS, False),
                ("flag_evaluations_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, True),
            )
            for response_name, response, expected in (
                ("true", True, ErrorsByLastValue(exposed_with_errors=1, unexposed_with_errors=0)),
                ("false", False, ErrorsByLastValue(exposed_with_errors=0, unexposed_with_errors=1)),
                ("no_response", None, ErrorsByLastValue(exposed_with_errors=0, unexposed_with_errors=0)),
            )
        ]
    )
    def test_an_error_takes_the_value_of_a_flag_call_where_the_mode_keeps_every_flag_call(
        self,
        _name: str,
        mode: FlagEvaluationsMode,
        calls_in_flag_evaluations: bool,
        response: bool | None,
        expected: ErrorsByLastValue,
    ) -> None:
        # A team on the native JSON events table reads flag calls from flag_evaluations on every mode.
        calls_in_flag_evaluations = calls_in_flag_evaluations or settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=EDITED_AT - timedelta(days=1),
        )
        calls = [("person-1", "new-checkout", {}), ("person-2", "org-beta", {"$group_0": "org-a"})]
        people = {distinct_id: create_person(team=self.team, distinct_ids=[distinct_id]) for distinct_id, _, _ in calls}
        people["person-3"] = create_person(team=self.team, distinct_ids=["person-3"])
        if not calls_in_flag_evaluations:
            for distinct_id, flag_key, properties in calls:
                _create_event(
                    team=self.team,
                    event="$feature_flag_called",
                    distinct_id=distinct_id,
                    timestamp=EDITED_AT + timedelta(minutes=1),
                    properties={**properties, "$feature_flag": flag_key, "$feature_flag_response": response},
                )
        for distinct_id, properties in (("person-1", {}), ("person-3", {"$group_0": "org-a"})):
            _create_event(
                team=self.team,
                event="$exception",
                distinct_id=distinct_id,
                timestamp=EDITED_AT + timedelta(minutes=2),
                properties=properties,
            )
        flush_persons_and_events()
        if calls_in_flag_evaluations:
            for distinct_id, flag_key, properties in calls:
                _create_flag_evaluations(
                    self.team.pk,
                    flag_key,
                    timestamp=EDITED_AT + timedelta(minutes=1),
                    distinct_id=distinct_id,
                    person_id=people[distinct_id].uuid,
                    response=response,
                    properties=properties,
                )
        group = dataclasses.replace(BOOLEAN, id="group", flag_key="org-beta", group_type_index=0)

        errors = errors_by_bucket(self.team, [BOOLEAN, group], EDITED_AT, EDITED_AT + WINDOW, WINDOW)

        self.assertEqual(
            {edit_id: bucket.since_edit.by_last_value for edit_id, [bucket] in errors.items()},
            {"boolean": expected, "group": expected},
        )

    def test_a_flag_call_tells_no_value_for_a_variant_named_like_a_boolean(self) -> None:
        self._send(
            [
                (
                    "person-1",
                    "$feature_flag_called",
                    1,
                    {"$feature_flag": "odd-variants", "$feature_flag_response": "false"},
                ),
                ("person-1", "$exception", 2, {}),
            ]
        )
        edit = dataclasses.replace(MULTIVARIATE, flag_key="odd-variants", variants=("false", "test"))

        self.assertEqual(
            self._since_edit(edit).by_last_value, ErrorsByLastValue(exposed_with_errors=0, unexposed_with_errors=0)
        )

    def test_errors_in_the_watched_conditions_split_by_reason_and_by_properties(self) -> None:
        def called(flag_key: str, reason: str, value: bool) -> dict[str, Any]:
            return {"$feature_flag": flag_key, "$feature_flag_reason": reason, f"$feature/{flag_key}": value}

        self._send(
            [
                ("person-1", "$feature_flag_called", 1, called("new-checkout", "Matched condition set 2", True)),
                ("person-1", "$exception", 2, {"$feature/new-checkout": True}),
                ("person-2", "$feature_flag_called", 3, called("new-checkout", "Out of rollout bound", False)),
                ("person-2", "$exception", 4, {"$feature/new-checkout": False}),
                ("person-3", "$feature_flag_called", 5, called("other-flag", "Matched condition set 2", True)),
                ("person-3", "$exception", 6, {"$feature/new-checkout": True}),
                ("person-4", "$exception", 7, {"$feature/new-checkout": True}),
            ],
            plans={"person-1": "pro", "person-2": "pro", "person-3": "free", "person-4": "pro"},
        )
        pro_plan = WatchedCondition(
            position=1, properties=({"key": "plan", "type": "person", "value": ["pro"], "operator": "exact"},)
        )

        errors = self._since_edit(dataclasses.replace(BOOLEAN, conditions=(pro_plan,)))

        self.assertEqual(
            errors.in_condition,
            {
                ConditionMatch.REASON: ConditionErrors(exposed_with_errors=1, unexposed_with_errors=1),
                ConditionMatch.PROPERTIES: ConditionErrors(exposed_with_errors=2, unexposed_with_errors=1),
            },
        )
