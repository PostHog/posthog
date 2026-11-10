from posthog.test.base import BaseTest

from parameterized import parameterized

from products.error_tracking.backend.facade.alerts import (
    compile_signal_source_filters,
    stored_issue_created_filter_outcome,
)
from products.error_tracking.backend.facade.contracts import LifecycleFilterOutcome
from products.error_tracking.backend.logic.assignees import assignee_property
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment

ASSIGNEE = "assignee"


class TestStoredIssueCreatedFilterOutcome(BaseTest):
    @parameterized.expand(
        [
            # No exception to read: a missing value must not pass a negated operator.
            (
                "exception_property_is_not",
                {"key": "$environment", "value": ["staging"], "operator": "is_not", "type": "event"},
                "high",
                LifecycleFilterOutcome.DATA_UNAVAILABLE,
            ),
            (
                "exception_property_is_not_set",
                {"key": "$environment", "operator": "is_not_set", "type": "event"},
                "high",
                LifecycleFilterOutcome.DATA_UNAVAILABLE,
            ),
            (
                "severity_matches",
                {"key": "severity", "value": ["high"], "operator": "exact", "type": "event"},
                "high",
                LifecycleFilterOutcome.MATCH,
            ),
            (
                "empty_severity_is_not_high",
                {"key": "severity", "value": ["high"], "operator": "exact", "type": "event"},
                None,
                LifecycleFilterOutcome.EXCLUDED_BY_FILTER,
            ),
            (
                "assignee_matches_the_alert_format",
                {"key": "assignee", "value": [ASSIGNEE], "operator": "exact", "type": "event"},
                None,
                LifecycleFilterOutcome.MATCH,
            ),
        ]
    )
    def test_outcome(self, _name: str, leaf: dict, severity: str | None, expected: LifecycleFilterOutcome) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError", severity=severity)
        ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=issue, user=self.user)
        if leaf.get("value") == [ASSIGNEE]:
            leaf = {**leaf, "value": [assignee_property({"type": "user", "id": self.user.id})]}
        filters = compile_signal_source_filters(self.team.id, {"properties": [leaf]})

        outcome = stored_issue_created_filter_outcome(self.team.id, str(issue.id), "fingerprint", filters)

        assert outcome == expected
