from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from queue import Queue
from time import monotonic

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections, connection, transaction

from products.error_tracking.backend.logic.issue_mutations import (
    assign_issue,
    bulk_update_issues,
    merge_issues,
    split_issue,
    update_issue,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueChange,
    ErrorTrackingIssueFingerprintV2,
)

EARLY = datetime(2026, 1, 1, tzinfo=UTC)
LATE = datetime(2026, 2, 1, tzinfo=UTC)


@patch("products.error_tracking.backend.logic.issue_changes.issue_change_log_enabled", return_value=True)
class TestIssueChangeRecording(BaseTest):
    def _create_issue(self, fingerprints: dict[str, datetime], **fields) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team, **fields)
        for fingerprint, first_seen in fingerprints.items():
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
            ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint=fingerprint).update(first_seen=first_seen)
        return issue

    def _changes(self) -> list[ErrorTrackingIssueChange]:
        return list(ErrorTrackingIssueChange.objects.for_team(self.team.id).order_by("kind", "issue_id"))

    def test_update_records_one_row_per_changed_field_in_one_operation(self, _flag) -> None:
        issue = self._create_issue({"fp": EARLY}, name="Old name")

        update_issue(
            self.team.id,
            issue.id,
            fields={"status": "resolved", "severity": "high", "name": "New name"},
            user=self.user,
            was_impersonated=False,
        )

        changes = self._changes()
        assert [(change.kind, change.data) for change in changes] == [
            ("name_changed", {"previous": "Old name"}),
            ("severity_changed", {"previous": None}),
            ("status_changed", {"previous": "active"}),
        ]
        assert {change.operation_id for change in changes} == {changes[0].operation_id}
        assert changes[0].snapshot == {
            "status": "resolved",
            "severity": "high",
            "name": "New name",
            "assignee": None,
            "first_seen": EARLY.isoformat(),
        }
        assert (changes[0].actor_type, changes[0].actor_user_id, changes[0].bulk) == ("user", self.user.id, False)

    def test_bulk_status_change_records_the_new_status_as_one_bulk_operation(self, _flag) -> None:
        issues = [self._create_issue({f"fp{i}": EARLY}) for i in range(2)]

        bulk_update_issues(
            self.team.id,
            [str(issue.id) for issue in issues],
            action="set_status",
            status="suppressed",
            assignee=None,
            user=self.user,
            was_impersonated=False,
        )

        changes = self._changes()
        assert len(changes) == 2
        assert {change.operation_id for change in changes} == {changes[0].operation_id}
        assert all(change.bulk for change in changes)
        assert [change.data["previous"] for change in changes] == ["active", "active"]
        assert [change.snapshot["status"] for change in changes] == ["suppressed", "suppressed"]

    def test_merge_records_the_merge_and_reopened_status_with_the_earliest_first_seen(self, _flag) -> None:
        target = self._create_issue({"target_fp": LATE}, status=ErrorTrackingIssue.Status.RESOLVED)
        source = self._create_issue({"source_fp": EARLY})

        merge_issues(self.team.id, target.id, [str(source.id)], user=self.user, was_impersonated=False)

        changes = self._changes()
        assert [(change.issue_id, change.kind, change.data) for change in changes] == [
            (target.id, "merged", {"merged_issue_ids": [str(source.id)]}),
            (target.id, "status_changed", {"previous": "resolved"}),
        ]
        assert {change.operation_id for change in changes} == {changes[0].operation_id}
        assert all(change.snapshot["status"] == "active" for change in changes)
        assert all(change.snapshot["first_seen"] == EARLY.isoformat() for change in changes)

    def test_split_records_the_split_and_a_created_row_per_new_issue(self, _flag) -> None:
        issue = self._create_issue({"fp_one": EARLY, "fp_two": LATE})

        [new_issue_id] = split_issue(
            self.team.id,
            issue.id,
            [{"fingerprint": "fp_two", "name": "Split issue"}],
            user=self.user,
            was_impersonated=False,
        )

        changes = self._changes()
        assert [(change.issue_id, change.kind, change.data) for change in changes] == [
            (new_issue_id, "created", {}),
            (issue.id, "split", {"new_issue_ids": [str(new_issue_id)]}),
        ]
        assert changes[0].snapshot["name"] == "Split issue"
        assert changes[0].snapshot["first_seen"] == LATE.isoformat()

    def test_assign_and_unassign_record_the_previous_assignee(self, _flag) -> None:
        issue = self._create_issue({"fp": EARLY})

        assign_issue(
            self.team.id, issue.id, {"type": "user", "id": self.user.id}, user=self.user, was_impersonated=False
        )
        assign_issue(self.team.id, issue.id, None, user=self.user, was_impersonated=False)

        changes = list(ErrorTrackingIssueChange.objects.for_team(self.team.id).order_by("created_at", "id"))
        assigned = {"type": "user", "id": str(self.user.id)}
        assert [(change.data, change.snapshot["assignee"]) for change in changes] == [
            ({"previous": None}, assigned),
            ({"previous": assigned}, None),
        ]

    def test_writes_nothing_when_the_flag_is_off(self, flag) -> None:
        flag.return_value = False
        issue = self._create_issue({"fp": EARLY})

        update_issue(self.team.id, issue.id, fields={"status": "resolved"}, user=self.user, was_impersonated=False)

        assert self._changes() == []


@patch("products.error_tracking.backend.logic.issue_changes.issue_change_log_enabled", return_value=True)
class TestIssueChangeRecordingConcurrency(NonAtomicBaseTest):
    def test_update_records_a_concurrent_committed_status_before_taking_the_row_lock(self, _flag) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, status=ErrorTrackingIssue.Status.RESOLVED)
        backend_pid: Queue[int] = Queue()

        def update() -> None:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SET statement_timeout = '15s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_pid.put(cursor.fetchone()[0])
                update_issue(
                    self.team.id,
                    issue.id,
                    fields={"status": "suppressed"},
                    user=self.user,
                    was_impersonated=False,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=1) as executor:
            with transaction.atomic():
                ErrorTrackingIssue.objects.filter(team_id=self.team.id, id=issue.id).update(
                    status=ErrorTrackingIssue.Status.ACTIVE
                )
                pending = executor.submit(update)
                pid = backend_pid.get(timeout=10)
                deadline = monotonic() + 10
                with connection.cursor() as cursor:
                    while True:
                        if pending.done():
                            pending.result()
                            self.fail("update completed before waiting for the concurrent status commit")
                        cursor.execute("SELECT cardinality(pg_blocking_pids(%s)) > 0", [pid])
                        if cursor.fetchone()[0]:
                            break
                        self.assertLess(monotonic(), deadline, "update did not wait for the issue row lock")
            pending.result(timeout=10)

        [change] = ErrorTrackingIssueChange.objects.for_team(self.team.id).all()
        assert (change.data, change.snapshot["status"]) == ({"previous": "active"}, "suppressed")
