from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from products.signals.backend.github_mention import replay
from products.signals.backend.models import GitHubPendingMention

ACCOUNT_ID = 4242


class TestReplayGitHubPendingMentions(BaseTest):
    def _pending(
        self, *, account_id: int = ACCOUNT_ID, age: timedelta, status: str = "pending"
    ) -> GitHubPendingMention:
        row = GitHubPendingMention.all_teams.create(
            team=self.team,
            github_account_id=account_id,
            github_login="octo",
            installation_id="42",
            repository="acme/app",
            pr_url="https://github.com/acme/app/pull/7",
            pr_number=7,
            comment_id=1000 + int(age.total_seconds()),
            status=status,
        )
        GitHubPendingMention.all_teams.filter(pk=row.pk).update(created_at=timezone.now() - age)
        return row

    def _run(self) -> None:
        replay.replay_github_pending_mentions(user_id=self.user.id, github_account_id=ACCOUNT_ID)

    def test_in_window_pending_is_replayed_and_marked_processed(self) -> None:
        row = self._pending(age=timedelta(hours=1))
        with patch.object(replay.process_github_mention, "delay") as delay:
            self._run()

        delay.assert_called_once()
        self.assertEqual(delay.call_args.kwargs["commenter_account_id"], ACCOUNT_ID)
        row.refresh_from_db()
        self.assertEqual(row.status, GitHubPendingMention.Status.PROCESSED)

    def test_expired_pending_is_skipped_not_replayed(self) -> None:
        row = self._pending(age=timedelta(hours=13))
        with patch.object(replay.process_github_mention, "delay") as delay:
            self._run()

        delay.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, GitHubPendingMention.Status.SKIPPED_EXPIRED)

    def test_already_processed_row_is_not_replayed(self) -> None:
        self._pending(age=timedelta(hours=1), status="processed")
        with patch.object(replay.process_github_mention, "delay") as delay:
            self._run()

        delay.assert_not_called()

    def test_other_accounts_pending_is_untouched(self) -> None:
        row = self._pending(account_id=9999, age=timedelta(hours=1))
        with patch.object(replay.process_github_mention, "delay") as delay:
            self._run()

        delay.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, GitHubPendingMention.Status.PENDING)
