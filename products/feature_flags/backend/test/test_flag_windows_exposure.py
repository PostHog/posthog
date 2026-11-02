import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS

from posthog.models import Team
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.flag_windows.exposure import (
    ConditionExposure,
    ExposureBucket,
    ExposureCounts,
    exposure_by_bucket,
)
from products.feature_flags.backend.flag_windows.query import ConditionMatch, WatchedCondition, WatchedEdit

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


class TestExposureByBucket(ClickhouseTestMixin, BaseTest):
    def _send(
        self, events: list[Event], event: str = "$pageview", people: dict[str, dict[str, Any]] | None = None
    ) -> None:
        people = people or {}
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, _, _ in events):
            create_person(team=self.team, distinct_ids=[distinct_id], properties=people.get(distinct_id, {}))
        for distinct_id, minutes, properties in events:
            _create_event(
                team=self.team,
                event=event,
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
                [(0, 2, 1, {})],
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
                [(0, 5, 4, {"control": 1, "test": 2})],
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
                [(0, 4, 3, {"control": 1, "false": 1})],
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
                [(0, 2, 1, {})],
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
                [(0, 4, 2, {})],
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
                [(0, 2, 0, {}), (20, 1, 1, {})],
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
                [(3, 1, 0, {}), (13, 1, 0, {}), (23, 1, 0, {}), (33, 1, 1, {})],
                (3, 35),
            ),
        ]
    )
    def test_exposure_by_bucket(
        self,
        _name: str,
        edit: WatchedEdit,
        events: list[Event],
        expected: list[tuple[int, int, int, dict[str, int]]],
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
                        ExposureCounts(with_flag=with_flag, exposed=exposed, by_variant=by_variant),
                    )
                    for minutes, with_flag, exposed, by_variant in expected
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
                        in_bucket=ExposureCounts(with_flag=2, exposed=1, by_variant={}),
                        since_edit=ExposureCounts(with_flag=2, exposed=1, by_variant={}),
                    ),
                    ExposureBucket(
                        start=START + timedelta(minutes=20),
                        in_bucket=ExposureCounts(with_flag=2, exposed=2, by_variant={}),
                        since_edit=ExposureCounts(with_flag=3, exposed=2, by_variant={}),
                    ),
                ]
            },
        )

    def test_counts_in_the_watched_conditions_by_reason_and_by_properties(self) -> None:
        def called(reason: str, value: bool, flag_key: str = "new-checkout") -> dict[str, Any]:
            return {"$feature_flag": flag_key, "$feature_flag_reason": reason, f"$feature/{flag_key}": value}

        self._send(
            [
                ("person-1", 1, called("Matched condition set 2", True)),
                ("person-2", 2, called("Out of rollout bound", False)),
                ("person-3", 3, called("Matched condition set 1", True)),
                ("person-4", 4, called("Evaluated locally", True)),
                ("person-5", 5, called("Matched condition set 1", True)),
                ("person-6", 6, called("Matched condition set 1", True, flag_key="other-flag")),
            ],
            event="$feature_flag_called",
            people={
                "person-1": {"plan": "pro"},
                "person-2": {"plan": "pro"},
                "person-3": {"plan": "free"},
                "person-4": {"plan": "pro"},
                "person-5": {"plan": "free"},
            },
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="person-5",
            timestamp=START - timedelta(minutes=5),
            properties=called("Matched condition set 2", True),
        )
        flush_persons_and_events()
        edit = dataclasses.replace(BOOLEAN, conditions=(PRO_PLAN,))
        other = dataclasses.replace(BOOLEAN, id="other", flag_key="other-flag", conditions=(EVERYONE,))

        exposure = exposure_by_bucket(self.team, [edit, other], START - timedelta(minutes=10), START + BUCKET, BUCKET)

        self.assertEqual(
            {edit_id: buckets[-1].since_edit.in_condition for edit_id, buckets in exposure.items()},
            {
                "boolean": {
                    ConditionMatch.REASON: ConditionExposure(with_flag=2, exposed=1),
                    ConditionMatch.PROPERTIES: ConditionExposure(with_flag=3, exposed=2),
                },
                "other": {
                    ConditionMatch.REASON: ConditionExposure(with_flag=1, exposed=1),
                    ConditionMatch.PROPERTIES: ConditionExposure(with_flag=1, exposed=1),
                },
            },
        )

    def test_a_relative_date_in_a_condition_counts_back_from_the_range_end(self) -> None:
        self._send(
            [("person-1", 1, {"$feature/new-checkout": True}), ("person-2", 2, {"$feature/new-checkout": True})],
            people={
                "person-1": {"signed_up_at": (START - timedelta(days=2)).isoformat()},
                "person-2": {"signed_up_at": (START - timedelta(days=9)).isoformat()},
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
            ConditionExposure(with_flag=1, exposed=1),
        )

    def test_a_condition_on_a_deleted_cohort_leaves_out_only_the_counts_by_properties_of_its_edit(self) -> None:
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
        )
        cohort = Cohort.objects.create(team=self.team, name="Beta testers", is_static=True, deleted=True)
        in_cohort = WatchedCondition(position=0, properties=({"key": "id", "type": "cohort", "value": cohort.pk},))
        broken = dataclasses.replace(BOOLEAN, conditions=(in_cohort,))
        healthy = dataclasses.replace(BOOLEAN, id="healthy", conditions=(EVERYONE,))

        exposure = exposure_by_bucket(self.team, [broken, healthy], START, START + BUCKET, BUCKET)

        self.assertEqual(
            {edit_id: buckets[0].in_bucket.in_condition for edit_id, buckets in exposure.items()},
            {
                "boolean": {ConditionMatch.REASON: ConditionExposure(with_flag=1, exposed=1)},
                "healthy": {
                    ConditionMatch.REASON: ConditionExposure(with_flag=1, exposed=1),
                    ConditionMatch.PROPERTIES: ConditionExposure(with_flag=1, exposed=1),
                },
            },
        )

    def test_counts_in_the_watched_conditions_of_a_group_flag_with_variants(self) -> None:
        def called(group: str, reason: str, value: str | bool) -> dict[str, Any]:
            return {
                "$feature_flag": "org-beta",
                "$feature_flag_reason": reason,
                "$feature/org-beta": value,
                "$group_0": group,
            }

        self._send(
            [
                ("person-1", 1, called("org-a", "Matched condition set 1", "control")),
                ("person-2", 2, called("org-a", "Matched condition set 1", "control")),
                ("person-3", 3, called("org-b", "Out of rollout bound", False)),
                ("person-4", 4, called("org-c", "Matched condition set 2", "test")),
            ],
            event="$feature_flag_called",
        )
        edit = dataclasses.replace(GROUP, variants=("control", "test"), conditions=(EVERYONE,))

        exposure = exposure_by_bucket(self.team, [edit], START, START + BUCKET, BUCKET)

        self.assertEqual(
            exposure[edit.id][0].in_bucket,
            ExposureCounts(
                with_flag=3,
                exposed=2,
                by_variant={"control": 1, "test": 1},
                in_condition={
                    ConditionMatch.REASON: ConditionExposure(with_flag=2, exposed=1),
                    ConditionMatch.PROPERTIES: ConditionExposure(with_flag=3, exposed=2),
                },
            ),
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
                        in_bucket=ExposureCounts(with_flag=1, exposed=1, by_variant={}),
                        since_edit=ExposureCounts(with_flag=1, exposed=1, by_variant={}),
                    ),
                ],
                "multivariate": [
                    ExposureBucket(
                        start=START,
                        in_bucket=ExposureCounts(with_flag=2, exposed=2, by_variant={"control": 1, "test": 1}),
                        since_edit=ExposureCounts(with_flag=2, exposed=2, by_variant={"control": 1, "test": 1}),
                    )
                ],
            },
        )


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
