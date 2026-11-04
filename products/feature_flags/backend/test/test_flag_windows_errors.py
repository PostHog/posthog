from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.test.persons import create_person

from products.error_tracking.backend.facade.testing import (
    create_issue,
    create_issue_fingerprint,
    sync_issue_to_clickhouse,
)
from products.feature_flags.backend.flag_windows.errors import ErrorCounts, errors_by_bucket
from products.feature_flags.backend.flag_windows.query import WatchedEdit

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
    def _send(self, events: list[Event]) -> None:
        for distinct_id in dict.fromkeys(distinct_id for distinct_id, _, _, _ in events):
            create_person(team=self.team, distinct_ids=[distinct_id])
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
                    with_errors=3, with_new_errors=0, exposed_with_errors=1, unexposed_with_errors=1, by_variant={}
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
                    with_errors=2, with_new_errors=0, exposed_with_errors=1, unexposed_with_errors=1, by_variant={}
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
