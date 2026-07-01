from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from uuid import UUID

import pytest
from freezegun import freeze_time
from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import patch

from django.db import close_old_connections, connection, transaction
from django.db.utils import IntegrityError

from posthog.models import Team

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingIssueMergeResult,
    ErrorTrackingSpikeEvent,
    ErrorTrackingSymbolSet,
)


class ErrorTrackingIssueTestMixin:
    team: Team

    def create_issue(self, fingerprints: list[str]) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        for fingerprint in fingerprints:
            ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)
        return issue


class TestErrorTracking(ErrorTrackingIssueTestMixin, BaseTest):
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

    def test_merge_missing_source_issue_is_noop(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])
        stale_issue_id = self.create_issue(["fingerprint_three"]).id
        ErrorTrackingIssue.objects.filter(id=stale_issue_id).delete()

        assert issue_two.merge(issue_ids=[issue_one.id, stale_issue_id]) == ErrorTrackingIssueMergeResult.STALE_ISSUES

        assert ErrorTrackingIssue.objects.filter(id=issue_one.id).exists()
        assert ErrorTrackingIssueFingerprintV2.objects.get(fingerprint="fingerprint_one").issue_id == issue_one.id
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_two.id).count() == 1

    def test_merge_stale_expected_fingerprint_issue_is_noop(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])
        issue_three = self.create_issue(["fingerprint_three"])

        assert (
            issue_two.merge(
                issue_ids=[issue_one.id],
                expected_fingerprint_issue_ids={
                    "fingerprint_one": issue_three.id,
                    "fingerprint_two": issue_two.id,
                },
            )
            == ErrorTrackingIssueMergeResult.STALE_FINGERPRINTS
        )

        assert ErrorTrackingIssue.objects.filter(id=issue_one.id).exists()
        assert ErrorTrackingIssueFingerprintV2.objects.get(fingerprint="fingerprint_one").issue_id == issue_one.id
        assert ErrorTrackingIssueFingerprintV2.objects.filter(issue_id=issue_two.id).count() == 1

    def test_merge_syncs_target_issue_to_clickhouse(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])

        with (
            patch("products.error_tracking.backend.models.update_error_tracking_issue_fingerprint_overrides"),
            patch("products.error_tracking.backend.models.sync_issues_to_clickhouse") as sync_issues_to_clickhouse,
            self.captureOnCommitCallbacks(execute=True),
        ):
            assert issue_two.merge(issue_ids=[issue_one.id]) == ErrorTrackingIssueMergeResult.MERGED

        sync_issues_to_clickhouse.assert_called_once_with(issue_ids=[issue_two.id], team_id=self.team.id)

    def test_merge_skips_clickhouse_side_effects_after_rollback(self):
        issue_one = self.create_issue(["fingerprint_one"])
        issue_two = self.create_issue(["fingerprint_two"])

        with (
            patch(
                "products.error_tracking.backend.models.update_error_tracking_issue_fingerprint_overrides"
            ) as update_overrides,
            patch("products.error_tracking.backend.models.sync_issues_to_clickhouse") as sync_issues_to_clickhouse,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
            pytest.raises(RuntimeError),
        ):
            with transaction.atomic():
                issue_two.merge(issue_ids=[issue_one.id])
                raise RuntimeError("roll back merge")

        assert callbacks == []
        update_overrides.assert_not_called()
        sync_issues_to_clickhouse.assert_not_called()
        assert ErrorTrackingIssue.objects.filter(id=issue_one.id).exists()
        assert ErrorTrackingIssueFingerprintV2.objects.get(fingerprint="fingerprint_one").issue_id == issue_one.id

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

    def test_split_syncs_original_and_new_issues_to_clickhouse(self):
        issue = self.create_issue(["fingerprint_one", "fingerprint_two"])

        with (
            patch("products.error_tracking.backend.models.update_error_tracking_issue_fingerprint_overrides"),
            patch("products.error_tracking.backend.models.sync_issues_to_clickhouse") as sync_issues_to_clickhouse,
            self.captureOnCommitCallbacks(execute=True),
        ):
            new_issues = issue.split(fingerprints=[{"fingerprint": "fingerprint_one"}])

        sync_issues_to_clickhouse.assert_called_once_with(
            issue_ids=[issue.id] + [new_issue.id for new_issue in new_issues], team_id=self.team.id
        )

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


class TestErrorTrackingMergeConcurrency(ErrorTrackingIssueTestMixin, NonAtomicBaseTest):
    def _run_merge(
        self, *, start_barrier: Barrier, target_issue_id: UUID, source_issue_ids: list[UUID]
    ) -> ErrorTrackingIssueMergeResult:
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '10s'")
                cursor.execute("SET statement_timeout = '15s'")
            start_barrier.wait(timeout=5)
            return ErrorTrackingIssue.objects.get(id=target_issue_id).merge(issue_ids=source_issue_ids)
        finally:
            close_old_connections()

    def test_concurrent_overlapping_merges_do_not_deadlock(self):
        source_issue_one = self.create_issue(["source_fingerprint_one"])
        source_issue_two = self.create_issue(["source_fingerprint_two"])
        target_issue_one = self.create_issue(["target_fingerprint_one"])
        target_issue_two = self.create_issue(["target_fingerprint_two"])
        start_barrier = Barrier(2)

        with (
            patch("products.error_tracking.backend.models.update_error_tracking_issue_fingerprint_overrides"),
            patch("products.error_tracking.backend.models.sync_issues_to_clickhouse"),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            merge_to_target_one = executor.submit(
                self._run_merge,
                start_barrier=start_barrier,
                target_issue_id=target_issue_one.id,
                source_issue_ids=[source_issue_one.id, source_issue_two.id],
            )
            merge_to_target_two = executor.submit(
                self._run_merge,
                start_barrier=start_barrier,
                target_issue_id=target_issue_two.id,
                source_issue_ids=[source_issue_two.id, source_issue_one.id],
            )

            merge_results = [merge_to_target_one.result(timeout=20), merge_to_target_two.result(timeout=20)]

        assert merge_results.count(ErrorTrackingIssueMergeResult.MERGED) == 1
        assert merge_results.count(ErrorTrackingIssueMergeResult.STALE_ISSUES) == 1
        assert not ErrorTrackingIssue.objects.filter(id__in=[source_issue_one.id, source_issue_two.id]).exists()
        assert ErrorTrackingIssue.objects.filter(id__in=[target_issue_one.id, target_issue_two.id]).count() == 2

        source_fingerprint_issue_ids = list(
            ErrorTrackingIssueFingerprintV2.objects.filter(
                fingerprint__in=["source_fingerprint_one", "source_fingerprint_two"]
            ).values_list("issue_id", flat=True)
        )
        assert len(source_fingerprint_issue_ids) == 2
        assert len(set(source_fingerprint_issue_ids)) == 1
