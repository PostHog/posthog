import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.error_tracking.backend.logic.issue_changes import (
    MAX_ISSUE_NAME_LENGTH,
    AssigneeRef,
    IssueSnapshot,
    parse_change_data,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueChange,
)

ROLE_ID = uuid.UUID("0190a1b2-c3d4-7000-8000-000000000001")
FIRST_SEEN = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
ISSUE_CREATED_AT = datetime(2026, 3, 1, tzinfo=UTC)
CHANGE_DATA_FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "issue_change_data.json").read_text())


class TestIssueSnapshot(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_assignee", None, "TypeError: boom", None, "TypeError: boom", FIRST_SEEN, FIRST_SEEN),
            (
                "user",
                ErrorTrackingIssueAssignment(user_id=42),
                "TypeError: boom",
                {"type": "user", "id": "42"},
                "TypeError: boom",
                FIRST_SEEN,
                FIRST_SEEN,
            ),
            (
                "role",
                ErrorTrackingIssueAssignment(role_id=ROLE_ID),
                None,
                {"type": "role", "id": str(ROLE_ID)},
                None,
                FIRST_SEEN,
                FIRST_SEEN,
            ),
            ("long_name", None, "x" * 2000, None, "x" * MAX_ISSUE_NAME_LENGTH, FIRST_SEEN, FIRST_SEEN),
            ("no_fingerprint_first_seen", None, "TypeError: boom", None, "TypeError: boom", None, ISSUE_CREATED_AT),
        ]
    )
    def test_to_json(
        self, _name, assignment, issue_name, expected_assignee, expected_name, first_seen, expected_first_seen
    ) -> None:
        issue = ErrorTrackingIssue(
            status=ErrorTrackingIssue.Status.RESOLVED,
            severity=ErrorTrackingIssue.Severity.HIGH,
            name=issue_name,
            created_at=ISSUE_CREATED_AT,
        )

        snapshot = IssueSnapshot.build(issue, assignee=AssigneeRef.from_assignment(assignment), first_seen=first_seen)

        assert snapshot.to_json() == {
            "status": "resolved",
            "severity": "high",
            "name": expected_name,
            "assignee": expected_assignee,
            "first_seen": expected_first_seen.isoformat(),
        }


class TestIssueChangeData(SimpleTestCase):
    @parameterized.expand([(f"{i}_{fixture['kind']}", fixture) for i, fixture in enumerate(CHANGE_DATA_FIXTURES)])
    def test_round_trips_shared_fixture(self, _name, fixture) -> None:
        parsed = parse_change_data(fixture["kind"], fixture["data"])

        assert parsed.kind == fixture["kind"]
        assert parsed.to_data() == fixture["data"]

    def test_every_kind_has_a_shared_fixture(self) -> None:
        assert {fixture["kind"] for fixture in CHANGE_DATA_FIXTURES} == set(ErrorTrackingIssueChange.Kind.values)
