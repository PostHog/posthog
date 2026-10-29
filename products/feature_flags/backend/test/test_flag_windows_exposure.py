from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.test.persons import create_person

from products.feature_flags.backend.flag_windows.exposure import ExposureBucket, WatchedEdit, exposure_by_bucket

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
BUCKET = timedelta(minutes=10)

BOOLEAN = WatchedEdit(id="boolean", flag_key="new-checkout", group_type_index=None, variants=(), enables=False)
MULTIVARIATE = WatchedEdit(
    id="multivariate", flag_key="pricing-test", group_type_index=None, variants=("control", "test"), enables=False
)
GROUP = WatchedEdit(id="group", flag_key="org-beta", group_type_index=0, variants=(), enables=False)
ENABLED = WatchedEdit(id="enabled", flag_key="new-checkout", group_type_index=None, variants=(), enables=True)

# (distinct id, minutes after START, event properties)
Event = tuple[str, int, dict[str, Any]]


class TestExposureByBucket(ClickhouseTestMixin, BaseTest):
    def _send(self, events: list[Event]) -> None:
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, _, _ in events):
            create_person(team=self.team, distinct_ids=[distinct_id])
        for distinct_id, minutes, properties in events:
            _create_event(
                team=self.team,
                event="$pageview",
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
                ],
                [(0, 4, 3, {"control": 1, "test": 2})],
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
                ],
                [(0, 2, 1, {})],
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
                    ("person-2", 34, {"$feature/new-checkout": True}),
                ],
                [(3, 1, 0, {}), (33, 1, 1, {})],
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
            exposure,
            {
                edit.id: [
                    ExposureBucket(
                        start=START + timedelta(minutes=minutes),
                        with_flag=with_flag,
                        exposed=exposed,
                        by_variant=by_variant,
                    )
                    for minutes, with_flag, exposed, by_variant in expected
                ]
            },
        )

    def test_one_query_keeps_the_counts_of_each_edit_apart(self) -> None:
        self._send(
            [
                ("person-1", 1, {"$feature/new-checkout": True, "$feature/pricing-test": "control"}),
                ("person-2", 2, {"$feature/new-checkout": False}),
                ("person-3", 3, {"$feature/pricing-test": "test"}),
                ("person-4", 40, {"$feature/new-checkout": True}),
            ]
        )

        exposure = exposure_by_bucket(self.team, [BOOLEAN, MULTIVARIATE], START, START + timedelta(minutes=30), BUCKET)

        self.assertEqual(
            exposure,
            {
                "boolean": [ExposureBucket(start=START, with_flag=2, exposed=1, by_variant={})],
                "multivariate": [
                    ExposureBucket(start=START, with_flag=2, exposed=2, by_variant={"control": 1, "test": 1})
                ],
            },
        )
