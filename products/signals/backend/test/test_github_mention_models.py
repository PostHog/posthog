from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models import Organization, Team

from products.signals.backend.models import GitHubPendingMention


class TestGitHubPendingMention(BaseTest):
    def _make(self, *, team: Team, account_id: int, status: str, created_delta: timedelta) -> GitHubPendingMention:
        row = GitHubPendingMention.objects.create(
            team=team,
            github_account_id=account_id,
            github_login="octocat",
            installation_id="42",
            repository="acme/app",
            pr_url="https://github.com/acme/app/pull/7",
            pr_number=7,
            comment_id=1000 + account_id,
            status=status,
        )
        # created_at is auto_now_add, so backdate explicitly for window assertions.
        GitHubPendingMention.all_teams.filter(pk=row.pk).update(created_at=timezone.now() - created_delta)
        return row

    def test_for_team_isolates_pending_mentions_across_teams(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org, name="other")
        self._make(team=self.team, account_id=1, status="pending", created_delta=timedelta())
        self._make(team=other_team, account_id=2, status="pending", created_delta=timedelta())

        mine = GitHubPendingMention.objects.for_team(self.team.id)

        self.assertEqual([r.github_account_id for r in mine], [1])

    def test_replay_lookup_matches_only_pending_rows_in_window(self) -> None:
        account_id = 55
        self._make(team=self.team, account_id=account_id, status="pending", created_delta=timedelta(hours=1))
        self._make(team=self.team, account_id=account_id, status="pending", created_delta=timedelta(hours=13))
        self._make(team=self.team, account_id=account_id, status="processed", created_delta=timedelta(hours=1))

        cutoff = timezone.now() - timedelta(hours=12)
        replayable = GitHubPendingMention.all_teams.filter(
            github_account_id=account_id,
            status=GitHubPendingMention.Status.PENDING,
            created_at__gte=cutoff,
        )

        self.assertEqual(replayable.count(), 1)
