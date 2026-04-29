from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db.utils import IntegrityError

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSpikeEvent,
    ErrorTrackingSymbolSet,
)


class TestErrorTracking(BaseTest):
    def create_issue(self, fingerprints) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        for fingerprint in fingerprints:
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue

    def test_defaults(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        assert issue.status == "active"
        assert issue.name is None

    def test_basic_merge(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])

        issue_two.merge(issue_ids=[issue_one.id])

        # remaps the first fingerprint to the second issue
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_two.id).count() == 2
        # bumps the version
        override = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_one").first()
        assert override
        assert override.version == 1

        # deletes issue one
        assert ErrorTrackingIssue.objects.count() == 1

    def test_merge_multiple_times(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])
        issue_three = self.create_issue(["fingerprint_three"])

        issue_two.merge(issue_ids=[issue_one.id])
        issue_three.merge(issue_ids=[issue_two.id])

        # only the third issue remains
        assert ErrorTrackingIssue.objects.count() == 1
        # all fingerprints point to the third issue
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_three.id).count() == 3

        # bumps versions of the merged issues correct number of times
        override = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_one").first()
        assert override
        assert override.version == 2
        override = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_two").first()
        assert override
        assert override.version == 1

    def test_merging_multiple_issues_at_once(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])
        issue_three = self.create_issue(["fingerprint_three"])

        issue_three.merge(issue_ids=[issue_one.id, issue_two.id])

        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_three.id).count() == 3

    def test_splitting_fingerprints(self):
        issue = self.create_issue(["fingerprint_one", "fingerprint_two", "fingerprint_three"])

        issue.split(
            fingerprints=[
                {"fingerprint": "fingerprint_one", "name": "Issue One", "description": "First issue"},
                {"fingerprint": "fingerprint_two"},
            ]
        )

        # creates two new issues
        assert ErrorTrackingIssue.objects.count() == 3

        # bumps the version but no longer points to the old issue
        override_one = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_one").first()
        assert override_one
        assert override_one.issue_id != issue.id
        assert override_one.version == 1

        override_two = ErrorTrackingIssueFingerprintV2.objects.filter(fingerprint="fingerprint_two").first()
        assert override_two
        # the overrides point to different issues
        assert override_one.issue_id != override_two.issue_id

        # new issues have the provided name and description
        new_issue_one = ErrorTrackingIssue.objects.get(id=override_one.issue_id)
        assert new_issue_one.name == "Issue One"
        assert new_issue_one.description == "First issue"

        new_issue_two = ErrorTrackingIssue.objects.get(id=override_two.issue_id)
        assert new_issue_two.name == "Untitled issue"
        assert new_issue_two.description is None

    def test_merge_reassigns_spike_events(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])

        spike_one = ErrorTrackingSpikeEvent.objects.create(
            team=self.team,
            issue=issue_one,
            detected_at=datetime.now(),
            computed_baseline=5.0,
            current_bucket_value=100,
        )
        spike_two = ErrorTrackingSpikeEvent.objects.create(
            team=self.team,
            issue=issue_two,
            detected_at=datetime.now(),
            computed_baseline=10.0,
            current_bucket_value=200,
        )

        issue_two.merge(issue_ids=[issue_one.id])

        # Both spike events now belong to issue_two
        assert ErrorTrackingSpikeEvent.objects.filter(issue=issue_two).count() == 2
        spike_one.refresh_from_db()
        assert spike_one.issue_id == issue_two.id
        spike_two.refresh_from_db()
        assert spike_two.issue_id == issue_two.id

    def test_split_deletes_spike_events(self):
        issue = self.create_issue(["fingerprint_one", "fingerprint_two"])

        ErrorTrackingSpikeEvent.objects.create(
            team=self.team, issue=issue, detected_at=datetime.now(), computed_baseline=5.0, current_bucket_value=100
        )
        ErrorTrackingSpikeEvent.objects.create(
            team=self.team, issue=issue, detected_at=datetime.now(), computed_baseline=10.0, current_bucket_value=200
        )

        assert ErrorTrackingSpikeEvent.objects.filter(issue=issue).count() == 2

        issue.split(fingerprints=[{"fingerprint": "fingerprint_one"}])

        # Spike events on the original issue are deleted
        assert ErrorTrackingSpikeEvent.objects.filter(issue=issue).count() == 0

    def test_error_tracking_issue_assignment_cascade_deletes(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user)

        assert ErrorTrackingIssueAssignment.objects.count() == 1
        issue.delete()
        assert ErrorTrackingIssueAssignment.objects.count() == 0

    def test_error_tracking_issue_assignment_uniqueness(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        with pytest.raises(IntegrityError):
            ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user)
            ErrorTrackingIssueAssignment.objects.create(issue=issue, user=self.user)

    @freeze_time("2025-01-01")
    def test_error_tracking_issue_first_seen_earliest_fingerprint(self):
        issue = self.create_issue(["fingerprint_one"])

        ten_minutes_ago = datetime.now() - timedelta(minutes=10)
        fingerprint = ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team, issue=issue, fingerprint="fingerprint_two", first_seen=ten_minutes_ago
        )

        # first_seen not accessible by default
        assert not hasattr(issue, "first_seen")

        issue = ErrorTrackingIssue.objects.with_first_seen().get(id=issue.id)
        assert issue.first_seen == fingerprint.first_seen

    def test_symbol_set_delete_calls_object_storage_delete(self):
        # Create a symbol set with a storage pointer
        symbol_set = ErrorTrackingSymbolSet.objects.create(
            team=self.team, ref="test-ref", storage_ptr="test-storage-path"
        )

        # Test that delete method calls object_storage.delete
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            with patch("posthog.storage.object_storage.delete") as mock_delete:
                symbol_set.delete()

                # Verify object storage delete was called with correct path
                mock_delete.assert_called_once_with(file_name="test-storage-path")
