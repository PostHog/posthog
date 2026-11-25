import dataclasses
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_flag_evaluations,
    flush_persons_and_events,
)
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS

from posthog.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.group.util import raw_create_group_ch
from posthog.test.persons import create_group_type_mapping, create_person

from products.cohorts.backend.models.cohort import Cohort
from products.event_definitions.backend.models.property_definition import PropertyDefinition
from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.flag_windows.exposure import ExposureBucket, ExposureCounts, exposure_by_bucket
from products.feature_flags.backend.flag_windows.query import (
    ConditionMatch,
    SplitCounts,
    WatchedCondition,
    WatchedEdit,
    split_counts,
)
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig
from products.feature_flags.backend.test.flag_window_fixtures import exposure_counts, split

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
BUCKET = timedelta(minutes=10)

BOOLEAN = WatchedEdit(
    id="boolean", flag_key="new-checkout", edited_at=START, group_type_index=None, variants=(), enables=False
)
MULTIVARIATE = WatchedEdit(
    id="multivariate",
    flag_key="pricing-test",
    edited_at=START,
    group_type_index=None,
    variants=("control", "test"),
    enables=False,
)
# A variant may be named "false", and only its JSON type tells it apart from a flag that evaluated to false.
FALSE_VARIANT = WatchedEdit(
    id="false-variant",
    flag_key="pricing-test",
    edited_at=START,
    group_type_index=None,
    variants=("control", "false"),
    enables=False,
)
GROUP = WatchedEdit(id="group", flag_key="org-beta", edited_at=START, group_type_index=0, variants=(), enables=False)
ENABLED = WatchedEdit(
    id="enabled", flag_key="new-checkout", edited_at=START, group_type_index=None, variants=(), enables=True
)

PRO_PLAN = WatchedCondition(
    position=1, properties=({"key": "plan", "type": "person", "value": ["pro"], "operator": "exact"},)
)
EVERYONE = WatchedCondition(position=0, properties=())

# (distinct id, minutes after START, event properties)
Event = tuple[str, int, dict[str, Any]]
# (bucket start in minutes after START, then the in_bucket exposed, unexposed and by_variant)
ExpectedBucket = tuple[int, int, int, dict[str, int]]


def _text_compared_with_a_number(team: Team) -> dict[str, Any]:
    PropertyDefinition.objects.create(
        team=team, name="age", property_type="Numeric", type=PropertyDefinition.Type.PERSON
    )
    return {"key": "age", "type": "person", "value": "abc", "operator": "gt"}


class TestExposureByBucket(ClickhouseTestMixin, BaseTest):
    def _send(
        self,
        events: Sequence[Event],
        event: str = "$pageview",
        people: dict[str, dict[str, Any]] | None = None,
        errors: Sequence[Event] = (),
    ) -> None:
        people = people or {}
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, _, _ in (*events, *errors)):
            create_person(team=self.team, distinct_ids=[distinct_id], properties=people.get(distinct_id, {}))
        for name, sent in ((event, events), ("$exception", errors)):
            for distinct_id, minutes, properties in sent:
                _create_event(
                    team=self.team,
                    event=name,
                    distinct_id=distinct_id,
                    timestamp=START + timedelta(minutes=minutes),
                    properties=properties,
                )
        flush_persons_and_events()

    @parameterized.expand(
        [
            (
                "boolean_flag_counts_people_with_true_among_people_with_the_flag",
                BOOLEAN,
                [
                    ("person-1", 1, {"$feature/new-checkout": True}),
                    ("person-1", 2, {"$feature/new-checkout": True}),
                    ("person-2", 3, {"$feature/new-checkout": False}),
                    ("person-3", 4, {"$feature/other-flag": True}),
                ],
                [(0, 1, 1, {})],
            ),
            (
                "multivariate_flag_counts_any_variant_and_each_variant",
                MULTIVARIATE,
                [
                    ("person-1", 1, {"$feature/pricing-test": "control"}),
                    ("person-2", 2, {"$feature/pricing-test": "test"}),
                    ("person-3", 3, {"$feature/pricing-test": "test"}),
                    ("person-4", 4, {"$feature/pricing-test": False}),
                    # A split under 100% serves true to a person who matches but draws no variant.
                    ("person-5", 5, {"$feature/pricing-test": True}),
                ],
                [(0, 4, 1, {"control": 1, "test": 2})],
            ),
            (
                "a_variant_named_false_counts_apart_from_a_flag_that_evaluated_to_false",
                FALSE_VARIANT,
                [
                    ("person-1", 1, {"$feature/pricing-test": "control"}),
                    ("person-2", 2, {"$feature/pricing-test": "false"}),
                    ("person-3", 3, {"$feature/pricing-test": False}),
                    ("person-4", 4, {"$feature/pricing-test": True}),
                ],
                [(0, 3, 1, {"control": 1, "false": 1})],
            ),
            (
                "group_flag_counts_groups_not_people",
                GROUP,
                [
                    ("person-1", 1, {"$feature/org-beta": True, "$group_0": "org-a"}),
                    ("person-2", 2, {"$feature/org-beta": True, "$group_0": "org-a"}),
                    ("person-3", 3, {"$feature/org-beta": False, "$group_0": "org-b"}),
                    ("person-4", 4, {"$feature/org-beta": True}),
                ],
                [(0, 1, 1, {})],
            ),
            (
                "enabling_edit_counts_people_that_loaded_flags",
                ENABLED,
                [
                    ("person-1", 1, {"$active_feature_flags": ["new-checkout"], "$feature/new-checkout": True}),
                    ("person-2", 2, {"$active_feature_flags": ["other-flag"], "$feature/other-flag": True}),
                    ("person-3", 3, {}),
                    # An app whose flags all evaluated to false still loaded flags.
                    ("person-4", 4, {"$active_feature_flags": [], "$feature/other-flag": False}),
                    # Server SDKs send the flag without `$active_feature_flags`.
                    ("person-5", 5, {"$feature/new-checkout": True}),
                ],
                [(0, 2, 2, {})],
            ),
            (
                "each_bucket_counts_its_own_events_and_a_bucket_without_the_flag_has_no_entry",
                BOOLEAN,
                [
                    ("person-1", 1, {"$feature/new-checkout": False}),
                    ("person-2", 2, {"$feature/new-checkout": False}),
                    ("person-1", 21, {"$feature/new-checkout": True}),
                    ("person-3", 15, {}),
                ],
                [(0, 0, 2, {}), (20, 1, 0, {})],
            ),
            (
                "buckets_start_at_the_window_start_so_the_last_bucket_is_kept",
                BOOLEAN,
                [
                    ("person-1", 4, {"$feature/new-checkout": False}),
                    ("person-1", 14, {"$feature/new-checkout": False}),
                    ("person-1", 24, {"$feature/new-checkout": False}),
                    ("person-2", 34, {"$feature/new-checkout": True}),
                ],
                [(3, 0, 1, {}), (13, 0, 1, {}), (23, 0, 1, {}), (33, 1, 0, {})],
                (3, 35),
            ),
        ]
    )
    def test_exposure_by_bucket(
        self,
        _name: str,
        edit: WatchedEdit,
        events: list[Event],
        expected: list[ExpectedBucket],
        window: tuple[int, int] = (0, 30),
    ) -> None:
        self._send(events)

        exposure = exposure_by_bucket(
            self.team, [edit], START + timedelta(minutes=window[0]), START + timedelta(minutes=window[1]), BUCKET
        )

        self.assertEqual(
            {
                edit_id: [(bucket.start, bucket.in_bucket) for bucket in buckets]
                for edit_id, buckets in exposure.items()
            },
            {
                edit.id: [
                    (
                        START + timedelta(minutes=minutes),
                        exposure_counts(split(exposed, unexposed), by_variant),
                    )
                    for minutes, exposed, unexposed, by_variant in expected
                ]
            },
        )

    def test_counts_since_the_edit_hold_each_person_once_and_skip_events_before_it(self) -> None:
        self._send(
            [
                ("person-1", 5, {"$feature/new-checkout": True}),
                ("person-1", 12, {"$feature/new-checkout": True}),
                ("person-2", 15, {"$feature/new-checkout": False}),
                ("person-1", 22, {"$feature/new-checkout": True}),
                ("person-3", 25, {"$feature/new-checkout": True}),
                ("person-2", 27, {"$feature/new-checkout": True}),
            ]
        )
        edit = dataclasses.replace(BOOLEAN, edited_at=START + timedelta(minutes=10))

        exposure = exposure_by_bucket(self.team, [edit], START, START + timedelta(minutes=30), BUCKET)

        self.assertEqual(
            exposure,
            {
                edit.id: [
                    ExposureBucket(
                        start=START + timedelta(minutes=10),
                        in_bucket=exposure_counts(split(1, 1)),
                        since_edit=exposure_counts(split(1, 1)),
                    ),
                    ExposureBucket(
                        start=START + timedelta(minutes=20),
                        in_bucket=exposure_counts(split(3, 0)),
                        since_edit=exposure_counts(split(3, 0)),
                    ),
                ]
            },
        )

    @parameterized.expand(
        [
            (
                "errors_count_under_the_value_on_their_event",
                BOOLEAN,
                [("person-1", 1, {"$feature/new-checkout": True}), ("person-2", 2, {"$feature/new-checkout": False})],
                [
                    ("person-3", 3, {"$feature/new-checkout": True}),
                    ("person-3", 4, {"$feature/new-checkout": True}),
                    ("person-4", 5, {"$feature/new-checkout": False}),
                    ("person-5", 6, {}),
                ],
                split(2, 2, errors=(1, 1)),
            ),
            (
                "a_person_who_switched_counts_only_as_exposed",
                BOOLEAN,
                [
                    ("person-1", 12, {"$feature/new-checkout": True}),
                    ("person-2", 1, {"$feature/new-checkout": False}),
                    ("person-3", 1, {"$feature/new-checkout": True}),
                ],
                [
                    ("person-1", 1, {"$feature/new-checkout": False}),
                    ("person-2", 12, {"$feature/new-checkout": True}),
                    ("person-3", 12, {"$feature/new-checkout": False}),
                    ("person-4", 12, {"$feature/new-checkout": False}),
                ],
                split(3, 1, errors=(1, 1)),
            ),
            (
                "an_error_of_any_variant_is_exposed",
                MULTIVARIATE,
                [],
                [
                    ("person-1", 1, {"$feature/pricing-test": "control"}),
                    ("person-2", 2, {"$feature/pricing-test": "test"}),
                    ("person-3", 3, {"$feature/pricing-test": False}),
                ],
                split(2, 1, errors=(2, 1)),
            ),
            (
                "an_error_of_an_app_that_loaded_flags_without_the_enabled_one_is_unexposed",
                ENABLED,
                [],
                [
                    ("person-1", 1, {"$feature/new-checkout": True}),
                    ("person-2", 2, {"$active_feature_flags": ["other-flag"], "$feature/other-flag": True}),
                ],
                split(1, 1, errors=(1, 1)),
            ),
        ]
    )
    def test_errors_since_the_edit(
        self, _name: str, edit: WatchedEdit, events: list[Event], errors: list[Event], expected: SplitCounts
    ) -> None:
        self._send(events, errors=errors)

        exposure = exposure_by_bucket(self.team, [edit], START, START + 2 * BUCKET, BUCKET)

        since_edit = exposure[edit.id][-1].since_edit
        self.assertEqual(
            {name: getattr(since_edit, name) for name in dataclasses.asdict(expected)}, dataclasses.asdict(expected)
        )

    def test_a_flag_above_the_exact_count_takes_the_unexposed_from_the_sample_of_its_people(self) -> None:
        candidates = [str(UUID(int=number)) for number in range(1, 200)]
        rows = sync_execute(
            "SELECT id FROM (SELECT arrayJoin(%(ids)s) AS id) WHERE modulo(cityHash64(toUUID(id)), 16) = 0",
            {"ids": candidates},
        )
        sampled = [row[0] for row in rows][:3]
        others = [candidate for candidate in candidates if candidate not in {row[0] for row in rows}][:3]
        on, off = {"$feature/new-checkout": True}, {"$feature/new-checkout": False}
        for person_uuid, event, properties in (
            (sampled[0], "$pageview", on),
            (sampled[1], "$exception", off),
            (sampled[2], "$pageview", off),
            (others[0], "$exception", on),
            (others[1], "$exception", off),
            (others[2], "$exception", off),
        ):
            create_person(team=self.team, distinct_ids=[person_uuid], uuid=person_uuid)
            _create_event(
                team=self.team,
                event=event,
                distinct_id=person_uuid,
                timestamp=START + timedelta(minutes=1),
                properties=properties,
            )
        flush_persons_and_events()

        with patch("products.feature_flags.backend.flag_windows.query.EXACT_COUNT", 3):
            exposure = exposure_by_bucket(self.team, [BOOLEAN], START, START + BUCKET, BUCKET)

        self.assertEqual(
            exposure[BOOLEAN.id][0].since_edit,
            ExposureCounts(
                with_flag=6,
                exposed=2,
                unexposed=2 * 16,
                exposed_with_errors=1,
                unexposed_with_errors=1 * 16,
                unexposed_one_in=16,
                by_variant={},
            ),
        )

    def test_counts_in_the_watched_conditions_by_reason_and_by_properties(self) -> None:
        def called(reason: str, value: bool, flag_key: str = "new-checkout") -> dict[str, Any]:
            return {"$feature_flag": flag_key, "$feature_flag_reason": reason, f"$feature/{flag_key}": value}

        self._send(
            [
                ("person-1", 1, called("Matched condition set 2", True)),
                ("person-1", 9, called("Matched condition set 2", False)),
                ("person-2", 2, called("Out of rollout bound", False)),
                ("person-3", 3, called("Matched condition set 1", True)),
                ("person-4", 4, called("Evaluated locally", True)),
                ("person-5", 5, called("Matched condition set 1", True)),
                ("person-6", 6, called("Matched condition set 1", True, flag_key="other-flag")),
                (
                    "person-7",
                    7,
                    {**called("Matched condition set 2", True, flag_key="other-flag"), "$feature/new-checkout": True},
                ),
                ("person-8", 2, called("Matched condition set 1", True, flag_key="other-flag")),
                ("person-9", 8, called("Matched condition set 3", True)),
                ("person-10", 9, called("Matched condition set 1", True)),
            ],
            event="$feature_flag_called",
            people={
                "person-1": {"plan": "pro"},
                "person-2": {"plan": "pro"},
                "person-3": {"plan": "free"},
                "person-4": {"plan": "pro"},
                "person-5": {"plan": "free"},
                "person-7": {"plan": "free"},
                "person-9": {"plan": "enterprise"},
                "person-10": {"plan": "pro", "beta": "yes"},
            },
            errors=[
                ("person-1", 9, {"$feature/new-checkout": True}),
                ("person-2", 3, {"$feature/new-checkout": False}),
                ("person-3", 4, {"$feature/new-checkout": True}),
                ("person-4", 5, {"$feature/new-checkout": True}),
            ],
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="person-5",
            timestamp=START - timedelta(minutes=5),
            properties=called("Matched condition set 2", True),
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="person-8",
            timestamp=START + timedelta(minutes=8),
            properties={"$feature/other-flag": True},
        )
        flush_persons_and_events()
        beta = ({"key": "beta", "type": "person", "value": ["yes"], "operator": "exact"},)
        enterprise = WatchedCondition(
            position=2, properties=({"key": "plan", "type": "person", "value": ["enterprise"], "operator": "exact"},)
        )
        on_another_flag = ({"key": "123", "type": "flag", "value": True, "operator": "flag_evaluates_to"},)
        edit = dataclasses.replace(
            BOOLEAN,
            conditions=(dataclasses.replace(PRO_PLAN, earlier_at_full_rollout=(beta, on_another_flag)), enterprise),
        )
        other = dataclasses.replace(
            BOOLEAN,
            id="other",
            flag_key="other-flag",
            edited_at=START + timedelta(minutes=3),
            conditions=(EVERYONE,),
        )

        exposure = exposure_by_bucket(self.team, [edit, other], START - timedelta(minutes=10), START + BUCKET, BUCKET)

        self.assertEqual(
            {edit_id: buckets[-1].since_edit.in_condition for edit_id, buckets in exposure.items()},
            {
                "boolean": {
                    ConditionMatch.REASON: split(2, 1, errors=(1, 1)),
                    ConditionMatch.PROPERTIES: split(3, 1, errors=(2, 1)),
                },
                "other": {
                    ConditionMatch.REASON: split(1, 0),
                    ConditionMatch.PROPERTIES: split(3, 0),
                },
            },
        )

    def test_a_relative_date_in_a_condition_counts_back_from_the_range_end(self) -> None:
        self.team.timezone = "Asia/Tokyo"
        self.team.save()
        self._send(
            [
                ("person-1", 1, {"$feature/new-checkout": True}),
                ("person-2", 2, {"$feature/new-checkout": True}),
                ("person-3", 3, {"$feature/new-checkout": True}),
            ],
            people={
                "person-1": {"signed_up_at": (START - timedelta(days=2)).isoformat()},
                "person-2": {"signed_up_at": (START - timedelta(days=9)).isoformat()},
                # Before the cutoff in UTC, but after it if the cutoff were read in the team's timezone.
                "person-3": {"signed_up_at": (START + BUCKET - timedelta(days=7, hours=3)).isoformat()},
            },
        )
        recent_sign_up = WatchedCondition(
            position=0,
            properties=({"key": "signed_up_at", "type": "person", "value": "-7d", "operator": "is_date_after"},),
        )
        edit = dataclasses.replace(BOOLEAN, conditions=(recent_sign_up,))

        exposure = exposure_by_bucket(self.team, [edit], START, START + BUCKET, BUCKET)

        self.assertEqual(
            exposure[edit.id][0].in_bucket.in_condition[ConditionMatch.PROPERTIES],
            split(1, 0),
        )

    @parameterized.expand(
        [
            (
                "deleted_static_cohort",
                lambda team: {
                    "key": "id",
                    "type": "cohort",
                    "value": Cohort.objects.create(team=team, name="Beta", is_static=True, deleted=True).pk,
                },
                True,
            ),
            ("cohort_id_not_a_number", lambda team: {"key": "id", "type": "cohort", "value": "beta"}, True),
            (
                "date_filter_without_a_string",
                lambda team: {"key": "signed_up_at", "type": "person", "value": 7, "operator": "is_date_after"},
                True,
            ),
            ("invalid_regex", lambda team: {"key": "email", "type": "person", "value": "(", "operator": "regex"}, True),
            # ClickHouse rejects these values only when the query runs, so no edit keeps its counts by properties.
            ("text_compared_with_a_number", _text_compared_with_a_number, False),
            (
                "date_that_clickhouse_cant_parse",
                lambda team: {"key": "signed_up_at", "type": "person", "value": "abc", "operator": "is_date_after"},
                False,
            ),
        ]
    )
    def test_a_condition_the_query_cant_evaluate_leaves_out_only_counts_by_properties(
        self,
        _name: str,
        broken_filter: Callable[[Team], dict[str, Any]],
        healthy_keeps_properties: bool,
    ) -> None:
        self._send(
            [
                (
                    "person-1",
                    1,
                    {
                        "$feature_flag": "new-checkout",
                        "$feature_flag_reason": "Matched condition set 1",
                        "$feature/new-checkout": True,
                    },
                )
            ],
            event="$feature_flag_called",
            people={"person-1": {"age": 30, "signed_up_at": "2026-09-01"}},
        )
        broken = dataclasses.replace(
            BOOLEAN, conditions=(WatchedCondition(position=0, properties=(broken_filter(self.team),)),)
        )
        healthy = dataclasses.replace(BOOLEAN, id="healthy", conditions=(EVERYONE,))

        exposure = exposure_by_bucket(self.team, [broken, healthy], START, START + BUCKET, BUCKET)

        by_reason = {ConditionMatch.REASON: split(1, 0)}
        by_reason_and_properties = {
            **by_reason,
            ConditionMatch.PROPERTIES: split(1, 0),
        }
        self.assertEqual(
            {edit_id: buckets[0].in_bucket for edit_id, buckets in exposure.items()},
            {
                "boolean": exposure_counts(split(1, 0), in_condition=by_reason),
                "healthy": exposure_counts(
                    split(1, 0),
                    in_condition=by_reason_and_properties if healthy_keeps_properties else by_reason,
                ),
            },
        )

    def test_counts_in_the_watched_conditions_of_a_group_flag_with_variants_next_to_a_person_flag(self) -> None:
        def called(group: str, reason: str, value: str | bool) -> dict[str, Any]:
            return {
                "$feature_flag": "org-beta",
                "$feature_flag_reason": reason,
                "$feature/org-beta": value,
                "$group_0": group,
            }

        # HogQL hides the group of an event sent before the group type existed.
        create_group_type_mapping(
            team=self.team,
            project_id=self.team.project_id,
            group_type="organization",
            group_type_index=0,
            created_at=START - timedelta(days=1),
        )
        # A group filter reads the ClickHouse groups table, which `create_group` leaves empty in tests.
        for group_key, tier in (("org-a", "enterprise"), ("org-b", "enterprise"), ("org-c", "free")):
            raw_create_group_ch(self.team.pk, 0, group_key, {"tier": tier}, created_at=START - timedelta(days=1))
        self._send(
            [
                ("person-1", 1, called("org-a", "Matched condition set 1", "control")),
                ("person-2", 2, called("org-a", "Matched condition set 1", "control")),
                ("person-3", 3, called("org-b", "Out of rollout bound", False)),
                ("person-4", 4, called("org-c", "Matched condition set 2", "test")),
                (
                    "person-5",
                    5,
                    {
                        "$feature_flag": "new-checkout",
                        "$feature_flag_reason": "Matched condition set 1",
                        "$feature/new-checkout": True,
                    },
                ),
            ],
            event="$feature_flag_called",
        )
        enterprise = WatchedCondition(
            position=0,
            properties=(
                {"key": "tier", "type": "group", "group_type_index": 0, "value": ["enterprise"], "operator": "exact"},
            ),
        )
        group_edit = dataclasses.replace(GROUP, variants=("control", "test"), conditions=(enterprise,))
        person_edit = dataclasses.replace(BOOLEAN, conditions=(EVERYONE,))

        exposure = exposure_by_bucket(self.team, [group_edit, person_edit], START, START + BUCKET, BUCKET)

        in_condition = {
            ConditionMatch.REASON: split(1, 0),
            ConditionMatch.PROPERTIES: split(1, 0),
        }
        self.assertEqual(
            {edit_id: buckets[0].in_bucket for edit_id, buckets in exposure.items()},
            {
                "group": exposure_counts(
                    split(2, 1),
                    by_variant={"control": 1, "test": 1},
                    in_condition={
                        ConditionMatch.REASON: split(1, 1),
                        ConditionMatch.PROPERTIES: split(1, 1),
                    },
                ),
                "boolean": exposure_counts(split(1, 0), in_condition=in_condition),
            },
        )

    @parameterized.expand(
        [
            # Ingestion still writes every flag call to events. On Cloud it also writes every flag call to flag_evaluations.
            ("read_flag_evaluations", FlagEvaluationsMode.READ_FLAG_EVALUATIONS),
            ("flag_evaluations_only", FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY),
        ]
    )
    def test_reads_the_flag_reasons_where_the_mode_keeps_every_flag_call(
        self, _name: str, mode: FlagEvaluationsMode
    ) -> None:
        # A team on the native JSON events table reads flag calls from flag_evaluations on every mode.
        calls_only_in_flag_evaluations = (
            mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY or settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA
        )
        OrganizationFeatureFlagsConfig.objects.update_or_create(
            organization=self.organization, defaults={"flag_evaluations_mode": mode}
        )
        person = create_person(team=self.team, distinct_ids=["person-1"])
        # The events copy names no matched condition, so only a scan of flag_evaluations counts the call.
        call = {
            "$feature_flag": "new-checkout",
            "$feature_flag_reason": "No condition sets matched",
            "$feature/new-checkout": True,
        }
        _create_event(
            team=self.team,
            event="$pageview" if calls_only_in_flag_evaluations else "$feature_flag_called",
            distinct_id="person-1",
            timestamp=START + timedelta(minutes=1),
            properties={"$feature/new-checkout": True} if calls_only_in_flag_evaluations else call,
        )
        flush_persons_and_events()
        _create_flag_evaluations(
            self.team.pk,
            "new-checkout",
            timestamp=START + timedelta(minutes=1),
            distinct_id="person-1",
            person_id=person.uuid,
            properties={"$feature_flag_reason": "Matched condition set 1"},
        )
        edit = dataclasses.replace(BOOLEAN, conditions=(EVERYONE,))

        exposure = exposure_by_bucket(self.team, [edit], START, START + BUCKET, BUCKET)

        self.assertEqual(
            exposure[edit.id][0].in_bucket.in_condition[ConditionMatch.REASON],
            split(1, 0),
        )

    def test_one_query_keeps_the_counts_of_each_edit_apart(self) -> None:
        self._send(
            [
                ("person-1", 1, {"$feature/new-checkout": True, "$feature/pricing-test": "control"}),
                ("person-2", 2, {"$feature/new-checkout": False}),
                ("person-3", 3, {"$feature/pricing-test": "test"}),
                ("person-4", 15, {"$feature/new-checkout": True}),
                ("person-5", 40, {"$feature/new-checkout": True}),
            ]
        )

        boolean = dataclasses.replace(BOOLEAN, edited_at=START + timedelta(minutes=10))

        exposure = exposure_by_bucket(self.team, [MULTIVARIATE, boolean], START, START + timedelta(minutes=30), BUCKET)

        self.assertEqual(
            exposure,
            {
                "boolean": [
                    ExposureBucket(
                        start=START + timedelta(minutes=10),
                        in_bucket=exposure_counts(split(1, 0)),
                        since_edit=exposure_counts(split(1, 0)),
                    ),
                ],
                "multivariate": [
                    ExposureBucket(
                        start=START,
                        in_bucket=exposure_counts(split(2, 0), by_variant={"control": 1, "test": 1}),
                        since_edit=exposure_counts(split(2, 0), by_variant={"control": 1, "test": 1}),
                    )
                ],
            },
        )


class TestSplitCounts(SimpleTestCase):
    @parameterized.expand(
        [
            # (exposed with errors, then per sample: with flag, exposed, exposed or with errors)
            ("every_count_exact", [20, 2_000, 1_000, 1_010, 125, 60, 61, 8, 4, 4], (1_000, 10, 1)),
            # `exposed` and the count with the errors are on both sides of 65,536, so their difference is noise.
            (
                "estimates_on_both_sides_of_the_limit_of_uniq",
                [1_308, 72_084, 65_415, 65_196, 4_505, 4_090, 4_099, 282, 256, 257],
                (415 * 16, 9 * 16, 16),
            ),
            (
                "the_second_sample_above_the_limit_too",
                [60_000, 3_000_000, 2_000_000, 2_010_000, 187_000, 125_000, 126_000, 11_700, 7_800, 7_840],
                (3_900 * 256, 40 * 256, 256),
            ),
            (
                "every_sample_above_the_limit",
                [0, 20_000_000, 19_000_000, 19_100_000, 1_250_000, 1_190_000, 1_190_100, 78_000, 78_100, 78_090],
                (0, 0, 256),
            ),
        ]
    )
    def test_the_unexposed_come_from_the_largest_exact_sample(
        self, _name: str, values: list[int], expected: tuple[int, int, int]
    ) -> None:
        result = split_counts(values)

        self.assertEqual(
            (result.with_flag, result.exposed, result.exposed_with_errors), (values[1], values[2], values[0])
        )
        self.assertEqual((result.unexposed, result.unexposed_with_errors, result.unexposed_one_in), expected)


class TestExposureByBucketInput(SimpleTestCase):
    @parameterized.expand(
        [
            ("fractional_bucket", START + timedelta(minutes=30), timedelta(seconds=1.5), [BOOLEAN]),
            (
                "more_buckets_than_hogql_returns",
                START + timedelta(seconds=MAX_SELECT_RETURNED_ROWS + 1),
                timedelta(seconds=1),
                [BOOLEAN],
            ),
            ("duplicate_edit_ids", START + timedelta(minutes=30), BUCKET, [BOOLEAN, BOOLEAN]),
            ("end_not_after_start", START, BUCKET, [BOOLEAN]),
        ]
    )
    def test_refuses_input_that_would_lose_or_mix_counts(
        self, _name: str, end: datetime, bucket: timedelta, edits: list[WatchedEdit]
    ) -> None:
        with self.assertRaises(ValueError):
            exposure_by_bucket(Team(), edits, START, end, bucket)
