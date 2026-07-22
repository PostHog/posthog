from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone as django_timezone

from posthog.models import Organization, Team, User

from products.tasks.backend.models import Channel, Task, TaskArtifact, TaskRun

PR_URL = "https://github.com/posthog/posthog/pull/321"


class BackfillGithubPrArtifactsTestCase(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="backfill@example.com", first_name="Ann", password="password")
        # Direct instantiation sidesteps the fail-closed TeamScopedManager (see test_presence.py).
        self.channel = Channel(team=self.team, name="growth", created_by=self.user)
        self.channel.save()
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            channel=self.channel,
            title="Fix the login redirect",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def _run(self, output, created_at=None, updated_at=None, task=None):
        run = TaskRun.objects.create(
            task=task or self.task, team=self.team, status=TaskRun.Status.COMPLETED, output=output
        )
        stamps = {}
        if created_at is not None:
            stamps["created_at"] = created_at
        if updated_at is not None:
            stamps["updated_at"] = updated_at
        if stamps:
            TaskRun.objects.filter(pk=run.pk).update(**stamps)
            run.refresh_from_db()
        return run

    def _call(self, *args) -> str:
        out = StringIO()
        call_command("backfill_github_pr_artifacts", *args, stdout=out)
        return out.getvalue()

    def _rows(self):
        return TaskArtifact.objects.for_team(self.team.id).filter(artifact_type=TaskArtifact.ArtifactType.GITHUB_PR)

    def test_dry_run_writes_nothing(self):
        self._run({"pr_url": PR_URL})
        out = self._call()
        self.assertEqual(self._rows().count(), 0)
        self.assertIn("1 would create", out)

    def test_live_creates_rows_with_provenance_and_chronology(self):
        first_ts = django_timezone.now() - timedelta(days=10)
        merge_ts = django_timezone.now() - timedelta(days=3)
        first = self._run({"pr_url": PR_URL}, created_at=first_ts, updated_at=first_ts)
        self._run({"pr_url": PR_URL, "pr_merged": True}, created_at=merge_ts, updated_at=merge_ts)

        self._call("--live")

        artifact = self._rows().get()
        self.assertEqual(artifact.task_id, self.task.id)
        self.assertEqual(artifact.task_run_id, first.id)
        self.assertEqual(artifact.channel_id, self.channel.id)
        self.assertEqual(artifact.created_by_id, self.user.id)
        self.assertEqual(artifact.name, "posthog/posthog#321")
        self.assertEqual(artifact.metadata["state"], "merged")
        self.assertEqual(artifact.created_at, first_ts)
        self.assertEqual(artifact.updated_at, merge_ts)

    def test_live_is_idempotent_and_skips_existing(self):
        self._run({"pr_url": PR_URL})
        self._call("--live")
        out = self._call("--live")
        self.assertEqual(self._rows().count(), 1)
        self.assertIn("0 created", out)
        self.assertIn("1 already exist", out)

    def test_skips_runs_of_deleted_tasks(self):
        self.task.deleted = True
        self.task.save()
        self._run({"pr_url": PR_URL})
        self._call("--live")
        self.assertEqual(self._rows().count(), 0)

    def test_team_filter_restricts_scope(self):
        self._run({"pr_url": PR_URL})
        self._call("--live", "--team-id", str(self.team.id + 1))
        self.assertEqual(self._rows().count(), 0)

    def test_merge_flag_pools_across_tasks_sharing_a_pr(self):
        # Task B's runs never saw pr_merged, but task A's did: both provenance rows must
        # land merged, with their historical timestamps intact (a fan-out after creation
        # would have bumped updated_at to now).
        a_ts = django_timezone.now() - timedelta(days=8)
        b_ts = django_timezone.now() - timedelta(days=6)
        other_task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            channel=self.channel,
            title="Follow up",
            description="d",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        self._run({"pr_url": PR_URL, "pr_merged": True}, created_at=a_ts, updated_at=a_ts)
        self._run({"pr_url": PR_URL}, created_at=b_ts, updated_at=b_ts, task=other_task)

        self._call("--live")

        rows = {row.task_id: row for row in self._rows()}
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[self.task.id].metadata["state"], "merged")
        self.assertEqual(rows[other_task.id].metadata["state"], "merged")
        self.assertEqual(rows[self.task.id].updated_at, a_ts)
        self.assertEqual(rows[other_task.id].updated_at, b_ts)
