from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from products.signals.backend.github_mention import result_relay


class TestRelayGitHubMentionResult(SimpleTestCase):
    def setUp(self) -> None:
        self.github = MagicMock()
        self.github.comment_on_pull_request.return_value = {"success": True}
        patch.object(result_relay.GitHubIntegration, "first_for_team_repository", return_value=self.github).start()

        self.mapping = SimpleNamespace(team_id=1, repository="acme/app", pr_number=7)
        self.first = patch.object(result_relay.GitHubMentionTaskMapping, "all_teams").start()
        self.first.filter.return_value.first.return_value = self.mapping
        self.addCleanup(patch.stopall)

    def _run(self, status: str) -> None:
        result_relay.relay_github_mention_result(run_id="run-1", status=status)

    def test_completed_posts_result_to_mapped_pr(self) -> None:
        self._run("completed")

        self.github.comment_on_pull_request.assert_called_once()
        repo, pr_number, body = self.github.comment_on_pull_request.call_args.args
        self.assertEqual((repo, pr_number), ("acme/app", 7))
        self.assertIn("pushed", body.lower())

    def test_failed_posts_failure_note(self) -> None:
        self._run("failed")

        body = self.github.comment_on_pull_request.call_args.args[2]
        self.assertIn("couldn't finish", body.lower())

    def test_no_mapping_posts_nothing(self) -> None:
        self.first.filter.return_value.first.return_value = None
        self._run("completed")
        self.github.comment_on_pull_request.assert_not_called()

    def test_unknown_status_posts_nothing(self) -> None:
        self._run("queued")
        self.github.comment_on_pull_request.assert_not_called()
