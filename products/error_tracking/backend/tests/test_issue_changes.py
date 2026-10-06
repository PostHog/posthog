import uuid
from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.issue_changes import (
    MAX_SNAPSHOT_NAME_LENGTH,
    IssueSnapshot,
    SnapshotAssignee,
)
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment

ROLE_ID = uuid.UUID("0190a1b2-c3d4-7000-8000-000000000001")
FIRST_SEEN = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


class TestIssueSnapshot(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_assignee", None, "TypeError: boom", None, "TypeError: boom"),
            (
                "user",
                ErrorTrackingIssueAssignment(user_id=42),
                "TypeError: boom",
                {"type": "user", "id": "42"},
                "TypeError: boom",
            ),
            ("role", ErrorTrackingIssueAssignment(role_id=ROLE_ID), None, {"type": "role", "id": str(ROLE_ID)}, None),
            ("long_name", None, "x" * 2000, None, "x" * MAX_SNAPSHOT_NAME_LENGTH),
        ]
    )
    def test_to_json(self, _name, assignment, issue_name, expected_assignee, expected_name) -> None:
        issue = ErrorTrackingIssue(
            status=ErrorTrackingIssue.Status.RESOLVED,
            severity=ErrorTrackingIssue.Severity.HIGH,
            name=issue_name,
            created_at=FIRST_SEEN,
        )

        snapshot = IssueSnapshot.build(issue, SnapshotAssignee.from_assignment(assignment))

        assert snapshot.to_json() == {
            "status": "resolved",
            "severity": "high",
            "name": expected_name,
            "assignee": expected_assignee,
            "first_seen": "2026-01-02T03:04:05+00:00",
        }
