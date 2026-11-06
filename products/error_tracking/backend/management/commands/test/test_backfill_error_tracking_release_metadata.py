from posthog.test.base import BaseTest

from products.error_tracking.backend.management.commands.backfill_error_tracking_release_metadata import Command
from products.error_tracking.backend.models import ErrorTrackingRelease


class TestBackfillErrorTrackingReleaseMetadata(BaseTest):
    def test_backfill_sanitizes_existing_remote_urls_in_batches(self) -> None:
        credential_release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="credential-release",
            version="1.0.0",
            project="example-project",
            metadata={
                "git": {
                    "commit_id": "abc123",
                    "remote_url": "https://deploy-user:fake-token@example.com/repository.git",
                }
            },
        )
        query_release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="query-release",
            version="1.0.1",
            project="example-project",
            metadata={
                "git": {
                    "commit_id": "def456",
                    "remote_url": "https://example.com/repository.git?access_token=fake-token#build",
                }
            },
        )
        clean_release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="clean-release",
            version="1.0.2",
            project="example-project",
            metadata={"git": {"remote_url": "git@example.com:group/repository.git"}, "provider": "example"},
        )

        Command().handle(live_run=False, batch_size=1, start_after_id=None)

        credential_release.refresh_from_db()
        query_release.refresh_from_db()
        assert credential_release.metadata == {
            "git": {
                "commit_id": "abc123",
                "remote_url": "https://deploy-user:fake-token@example.com/repository.git",
            }
        }
        assert query_release.metadata == {
            "git": {
                "commit_id": "def456",
                "remote_url": "https://example.com/repository.git?access_token=fake-token#build",
            }
        }

        Command().handle(live_run=True, batch_size=1, start_after_id=None)
        Command().handle(live_run=True, batch_size=1, start_after_id=None)

        credential_release.refresh_from_db()
        query_release.refresh_from_db()
        clean_release.refresh_from_db()
        assert credential_release.metadata == {
            "git": {"commit_id": "abc123", "remote_url": "https://example.com/repository.git"}
        }
        assert query_release.metadata == {
            "git": {"commit_id": "def456", "remote_url": "https://example.com/repository.git"}
        }
        assert clean_release.metadata == {
            "git": {"remote_url": "git@example.com:group/repository.git"},
            "provider": "example",
        }
