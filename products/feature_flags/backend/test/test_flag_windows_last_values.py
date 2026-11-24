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

from parameterized import param, parameterized

from posthog.dataclasses import frozen
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.test.persons import create_group_type_mapping, create_person

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.facade.flags import reads_flag_calls_without_events_fallback
from products.feature_flags.backend.flag_windows import query as flag_window_query
from products.feature_flags.backend.flag_windows.last_values import LOOKBACK, LastValueCounts, last_values_by_bucket
from products.feature_flags.backend.flag_windows.query import WatchedEdit
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

EDITED_AT = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
BUCKET = timedelta(minutes=30)
LOOKBACK_MINUTES = int(LOOKBACK / timedelta(minutes=1))

BOOLEAN = WatchedEdit(
    id="boolean", flag_key="new-checkout", edited_at=EDITED_AT, group_type_index=None, variants=(), enables=False
)
ENABLED = dataclasses.replace(BOOLEAN, id="enabled", enables=True)
MULTIVARIATE = dataclasses.replace(BOOLEAN, id="multivariate", variants=("control", "test"))
FALSE_VARIANT = dataclasses.replace(BOOLEAN, id="false-variant", variants=("control", "false"))
GROUP = dataclasses.replace(BOOLEAN, id="group", flag_key="org-beta", group_type_index=0)

LOADED_OTHER_FLAGS = {"$active_feature_flags": ["other"], "$feature/other": True}


@frozen
class Sent:
    event: str
    # After the edit.
    minutes: int
    properties: dict[str, Any]
    distinct_id: str


def pageview(
    minutes: int, value: bool | None = None, distinct_id: str = "person", properties: dict[str, Any] | None = None
) -> Sent:
    carried = {} if value is None else {"$feature/new-checkout": value}
    return Sent(
        event="$pageview", minutes=minutes, properties={**carried, **(properties or {})}, distinct_id=distinct_id
    )


def error(
    minutes: int, value: bool | None = None, distinct_id: str = "person", properties: dict[str, Any] | None = None
) -> Sent:
    return dataclasses.replace(pageview(minutes, value, distinct_id, properties), event="$exception")


def call(
    minutes: int,
    response: bool | str | None,
    flag_key: str = "new-checkout",
    distinct_id: str = "person",
    properties: dict[str, Any] | None = None,
) -> Sent:
    # A minimal flag call doesn't carry `$feature/<key>`.
    return Sent(
        event="$feature_flag_called",
        minutes=minutes,
        properties={"$feature_flag": flag_key, "$feature_flag_response": response, **(properties or {})},
        distinct_id=distinct_id,
    )


def counts(exposed: int = 0, unexposed: int = 0, errors: tuple[int, int] = (0, 0), people: int = 1) -> LastValueCounts:
    return LastValueCounts(
        with_flag=people,
        exposed=exposed,
        unexposed=unexposed,
        exposed_with_errors=errors[0],
        unexposed_with_errors=errors[1],
    )


NOBODY = counts(people=0)


class TestLastValuesByBucket(ClickhouseTestMixin, BaseTest):
    def _send(self, sent: list[Sent]) -> None:
        # HogQL hides the group of an event sent before the group type existed.
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=EDITED_AT - timedelta(days=30),
        )
        people = {
            distinct_id: create_person(team=self.team, distinct_ids=[distinct_id])
            for distinct_id in dict.fromkeys(item.distinct_id for item in sent)
        }
        calls_outside_events = reads_flag_calls_without_events_fallback(self.team)
        for item in sent:
            timestamp = EDITED_AT + timedelta(minutes=item.minutes)
            if item.event == "$feature_flag_called" and calls_outside_events:
                response = item.properties["$feature_flag_response"]
                _create_flag_evaluations(
                    self.team.pk,
                    item.properties["$feature_flag"],
                    timestamp=timestamp,
                    distinct_id=item.distinct_id,
                    person_id=people[item.distinct_id].uuid,
                    response=response,
                    properties=item.properties,
                )
                continue
            _create_event(
                team=self.team,
                event=item.event,
                distinct_id=item.distinct_id,
                timestamp=timestamp,
                properties=item.properties,
            )
        flush_persons_and_events()

    def _since_edit(
        self, edits: list[WatchedEdit], start: datetime = EDITED_AT, buckets: int = 1
    ) -> dict[str, LastValueCounts]:
        counted = last_values_by_bucket(self.team, edits, start, start + buckets * BUCKET, BUCKET)
        return {edit_id: rows[-1].since_edit if rows else NOBODY for edit_id, rows in counted.items()}

    @parameterized.expand(
        [
            param("call_before_the_error", [call(1, True), error(2)], counts(exposed=1, errors=(1, 0))),
            param("call_counts_as_an_event", [call(1, False)], counts(unexposed=1)),
            param("call_of_another_flag", [call(1, True, flag_key="other-flag"), error(2)], NOBODY),
            param("call_without_a_response", [call(1, None), error(2)], NOBODY),
            param("call_after_the_only_error", [error(1), call(2, True)], counts(exposed=1)),
            param("call_from_before_the_edit", [call(-60, False), error(2)], counts(unexposed=1, errors=(0, 1))),
            param("call_without_an_event_after_the_edit", [call(-60, False), pageview(-5)], NOBODY),
            param("call_from_before_the_lookback", [call(-LOOKBACK_MINUTES - 1, False), error(2)], NOBODY),
            param("event_from_before_the_edit", [pageview(-60, True), error(2)], NOBODY),
            param(
                "value_changes_between_two_errors",
                [call(-60, False), error(2), call(5, True), error(8)],
                counts(exposed=1, unexposed=1, errors=(1, 1)),
            ),
            param(
                "value_changes_before_the_only_error",
                [call(-60, False), pageview(2), call(5, True), error(8)],
                counts(exposed=1, unexposed=1, errors=(1, 0)),
            ),
            param(
                "value_changes_at_the_first_event",
                [call(-60, False), call(5, True), error(8)],
                counts(exposed=1, errors=(1, 0)),
            ),
            param(
                "event_after_a_call_wins",
                [call(1, True), pageview(2, False), error(3)],
                counts(exposed=1, unexposed=1, errors=(0, 1)),
            ),
            param(
                "call_after_an_event_wins",
                [pageview(1, False), call(2, True), error(3)],
                counts(exposed=1, unexposed=1, errors=(1, 0)),
            ),
            param(
                "value_on_the_error_wins",
                [call(1, True), error(2, False)],
                counts(exposed=1, unexposed=1, errors=(0, 1)),
            ),
            param("variant", [call(1, "test"), error(2)], counts(exposed=1, errors=(1, 0)), MULTIVARIATE),
            param(
                "variant_flag_that_is_false",
                [call(1, False), error(2)],
                counts(unexposed=1, errors=(0, 1)),
                MULTIVARIATE,
            ),
            # The response of a call is text, so it can't tell the variant from a flag that evaluated to false.
            param("variant_named_false", [call(1, "false"), error(2)], NOBODY, FALSE_VARIANT),
            param("true_from_before_an_edit_that_enables", [call(-60, True), error(2)], NOBODY, ENABLED),
            param(
                "false_from_before_an_edit_that_enables",
                [call(-60, False), error(2)],
                counts(unexposed=1, errors=(0, 1)),
                ENABLED,
            ),
            param(
                "loaded_flags_without_this_one",
                [pageview(1, properties=LOADED_OTHER_FLAGS), error(2)],
                counts(unexposed=1, errors=(0, 1)),
                ENABLED,
            ),
            param(
                "loaded_flags_without_this_one_after_a_call",
                [call(1, True), pageview(2, properties=LOADED_OTHER_FLAGS), error(3)],
                counts(exposed=1, errors=(1, 0)),
                ENABLED,
            ),
            param(
                "loaded_flags_without_this_one_before_a_call",
                [pageview(1, properties=LOADED_OTHER_FLAGS), call(2, True), error(3)],
                counts(exposed=1, unexposed=1, errors=(1, 0)),
                ENABLED,
            ),
        ]
    )
    def test_counts_since_the_edit(
        self, _name: str, sent: list[Sent], expected: LastValueCounts, edit: WatchedEdit = BOOLEAN
    ) -> None:
        self._send(sent)

        self.assertEqual(self._since_edit([edit]), {edit.id: expected})

    def test_a_value_holds_in_later_buckets_until_a_newer_one(self) -> None:
        self._send(
            [
                call(1, False),
                # No event in the second bucket.
                error(65),
                call(95, True),
                error(125),
                call(5, True, distinct_id="other-person"),
                error(70, distinct_id="other-person"),
            ]
        )

        buckets = last_values_by_bucket(self.team, [BOOLEAN], EDITED_AT, EDITED_AT + 5 * BUCKET, BUCKET)

        self.assertEqual(
            [(bucket.start, bucket.in_bucket, bucket.since_edit) for bucket in buckets["boolean"]],
            [
                (EDITED_AT, counts(1, 1, people=2), counts(1, 1, people=2)),
                (EDITED_AT + 2 * BUCKET, counts(1, 1, (1, 1), people=2), counts(1, 1, (1, 1), people=2)),
                (EDITED_AT + 3 * BUCKET, counts(1, 0), counts(2, 1, (1, 1), people=2)),
                (EDITED_AT + 4 * BUCKET, counts(1, 0, (1, 0)), counts(2, 1, (2, 1), people=2)),
            ],
        )

    def test_a_call_from_between_the_edit_and_the_range_start_counts_but_an_event_does_not(self) -> None:
        self._send(
            [
                call(5, True, distinct_id="called"),
                error(40, distinct_id="called"),
                pageview(5, True, distinct_id="carried"),
                error(40, distinct_id="carried"),
            ]
        )

        self.assertEqual(
            self._since_edit([BOOLEAN], start=EDITED_AT + BUCKET), {"boolean": counts(exposed=1, errors=(1, 0))}
        )

    def test_an_edit_that_enables_reads_later_buckets_and_calls_from_before_the_range(self) -> None:
        self._send(
            [
                pageview(1, distinct_id="loaded", properties=LOADED_OTHER_FLAGS),
                error(40, distinct_id="loaded"),
                error(70, distinct_id="loaded"),
                call(5, True, distinct_id="called"),
                error(70, distinct_id="called"),
            ]
        )

        self.assertEqual(
            self._since_edit([ENABLED], buckets=2), {"enabled": counts(exposed=1, unexposed=1, errors=(0, 1), people=2)}
        )
        self.assertEqual(
            self._since_edit([ENABLED], start=EDITED_AT + BUCKET, buckets=2),
            {"enabled": counts(exposed=1, errors=(1, 0))},
        )

    def test_edits_with_their_own_flags_times_and_actors(self) -> None:
        self._send(
            [
                # Between the two edits, so only the earlier one counts the pageview.
                pageview(-10, True, distinct_id="person-1"),
                error(-5, distinct_id="person-1"),
                call(1, True, flag_key="other-flag", distinct_id="person-2"),
                error(2, distinct_id="person-2"),
                # Another person of the same group gives the group's value.
                call(1, True, flag_key="org-beta", distinct_id="person-3", properties={"$group_0": "org-a"}),
                error(2, distinct_id="person-4", properties={"$group_0": "org-a"}),
                call(1, False, flag_key="org-beta", distinct_id="person-5"),
            ]
        )
        earlier = dataclasses.replace(BOOLEAN, id="earlier", edited_at=EDITED_AT - timedelta(minutes=20))
        other = dataclasses.replace(BOOLEAN, id="other", flag_key="other-flag")

        self.assertEqual(
            self._since_edit([BOOLEAN, earlier, other, GROUP], start=EDITED_AT - BUCKET, buckets=2),
            {
                "boolean": NOBODY,
                "earlier": counts(exposed=1, errors=(1, 0)),
                "other": counts(exposed=1, errors=(1, 0)),
                "group": counts(exposed=1, errors=(1, 0)),
            },
        )

    def test_reads_calls_that_are_only_in_flag_evaluations(self) -> None:
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization,
            defaults={"flag_evaluations_mode": FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY},
        )
        self._send(
            [
                call(-60, False, distinct_id="person-1"),
                error(2, distinct_id="person-1"),
                call(1, True, distinct_id="person-2"),
                call(1, "test", distinct_id="person-3"),
                error(2, distinct_id="person-3"),
                call(1, None, distinct_id="person-4"),
                # A call of another watched flag is no event of this one.
                call(-60, False, distinct_id="person-5"),
                call(1, True, flag_key="org-beta", distinct_id="person-5", properties={"$group_0": "org-a"}),
                error(2, distinct_id="person-6", properties={"$group_0": "org-a"}),
            ]
        )

        self.assertEqual(
            self._since_edit([BOOLEAN, MULTIVARIATE, GROUP]),
            {
                # A boolean flag serves no variant.
                "boolean": counts(1, 2, (0, 2), people=3),
                "multivariate": counts(2, 1, (1, 1), people=3),
                "group": counts(1, 0, (1, 0)),
            },
        )

    @parameterized.expand(
        [
            ("timeout", ClickHouseQueryTimeOut),
            ("memory", ClickHouseQueryMemoryLimitExceeded),
            ("estimated_too_slow", ClickHouseEstimatedQueryExecutionTimeTooLong),
        ]
    )
    def test_a_query_that_runs_out_leaves_out_only_its_edits(self, _name: str, raised: type[Exception]) -> None:
        run_query = flag_window_query.execute_hogql_query
        results = iter([raised(), None])

        def fail_first(*args: Any, **kwargs: Any) -> Any:
            if error := next(results):
                raise error
            return run_query(*args, **kwargs)

        # One query per kind of actor, so the group edit keeps its counts.
        with patch.object(flag_window_query, "execute_hogql_query", side_effect=fail_first):
            self.assertEqual(self._since_edit([BOOLEAN, GROUP]), {"group": NOBODY})
