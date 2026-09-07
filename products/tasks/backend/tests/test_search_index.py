from django.test import TransactionTestCase

from posthog.models import Organization, Team, User
from posthog.models.scoping import team_scope

from products.tasks.backend.facade.api import search_tasks, set_task_title
from products.tasks.backend.models import Channel, Task, TaskArtifact, TaskRun, TaskSearchDocument
from products.tasks.backend.search_index import (
    MAX_INDEXED_ARTIFACTS,
    MAX_INDEXED_PR_URLS,
    index_task_artifact,
    index_task_run,
)


class TestTaskSearchIndex(TransactionTestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Search Org")
        self.team = Team.objects.create(organization=self.organization, name="Search Team")
        self.user = User.objects.create(email="search@example.com", distinct_id="search-user")
        self.enterContext(team_scope(self.team.id))

    def make_task(self, title="Index command menu", **kwargs):
        channel = kwargs.pop("channel", None) or Channel.objects.create(
            team=self.team, name=f"space-{Task.objects.count()}", created_by=self.user
        )
        return Task.objects.create(
            team=self.team,
            title=title,
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
            repository="posthog/posthog",
            channel=channel,
            **kwargs,
        )

    def test_indexes_pr_url_number_and_artifact_name(self):
        task = self.make_task()
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            output={"pr_urls": ["https://github.com/PostHog/posthog/pull/123"]},
            artifacts=[{"id": "report", "name": "search-report.csv", "type": "output"}],
        )
        index_task_run(run.id)

        pr_result = search_tasks(self.team.id, self.user.id, "123")[0]
        self.assertEqual(pr_result["kind"], TaskSearchDocument.Kind.PULL_REQUEST)
        self.assertEqual(pr_result["metadata"]["url"], "https://github.com/PostHog/posthog/pull/123")

        artifact_result = search_tasks(self.team.id, self.user.id, "search-report")[0]
        self.assertEqual(artifact_result["kind"], TaskSearchDocument.Kind.ARTIFACT)
        self.assertEqual(artifact_result["task_id"], str(task.id))

    def test_short_queries_only_match_exact_identifiers(self):
        task = self.make_task(title="A common title")
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            artifacts=[{"id": "short", "name": "x"}],
        )
        index_task_run(run.id)

        self.assertEqual(search_tasks(self.team.id, self.user.id, "a"), [])
        self.assertEqual(search_tasks(self.team.id, self.user.id, "x")[0]["kind"], TaskSearchDocument.Kind.ARTIFACT)

    def test_searches_pr_url_with_noncanonical_suffix(self):
        task = self.make_task()
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            output={"pr_url": "https://github.com/PostHog/posthog/pull/123"},
        )
        index_task_run(run.id)

        result = search_tasks(self.team.id, self.user.id, "https://github.com/posthog/posthog/pull/123/files")[0]

        self.assertEqual(result["kind"], TaskSearchDocument.Kind.PULL_REQUEST)

    def test_replaces_documents_when_run_output_changes(self):
        task = self.make_task()
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            output={"pr_url": "https://github.com/posthog/posthog/pull/10"},
        )
        index_task_run(run.id)
        run.output = {"pr_url": "https://github.com/posthog/posthog/pull/11"}
        run.save(update_fields=["output"])
        index_task_run(run.id)

        self.assertEqual(search_tasks(self.team.id, self.user.id, "10"), [])
        self.assertEqual(search_tasks(self.team.id, self.user.id, "11")[0]["title"], "PR #11")

    def test_indexes_automated_task_title_updates(self):
        task = self.make_task(title="Researching report")

        self.assertTrue(set_task_title(task.id, self.team.id, "Research: Search indexing"))

        self.assertEqual(search_tasks(self.team.id, self.user.id, "search indexing")[0]["task_id"], str(task.id))

    def test_updates_descendant_context_without_reindexing_runs(self):
        task = self.make_task(title="Old title")
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            artifacts=[{"id": "report", "name": "report.csv"}],
        )
        index_task_run(run.id)
        new_channel = Channel.objects.create(team=self.team, name="new-space", created_by=self.user)

        task.title = "New title"
        task.channel = new_channel
        task.save(update_fields=["title", "channel"])

        document = TaskSearchDocument.objects.for_team(self.team.id).get(
            kind=TaskSearchDocument.Kind.ARTIFACT,
            task_run_id=run.id,
        )
        self.assertEqual(document.subtitle, "New title")
        self.assertEqual(document.channel_id, new_channel.id)
        self.assertIn("new title", document.search_text)

    def test_limits_pr_documents_from_run_output(self):
        task = self.make_task()
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            output={
                "pr_urls": [
                    f"https://github.com/PostHog/posthog/pull/{number}" for number in range(MAX_INDEXED_PR_URLS + 10)
                ]
            },
        )

        index_task_run(run.id)

        self.assertEqual(
            TaskSearchDocument.objects.for_team(self.team.id)
            .filter(kind=TaskSearchDocument.Kind.PULL_REQUEST, task_run_id=run.id)
            .count(),
            MAX_INDEXED_PR_URLS,
        )

    def test_limits_artifact_documents_from_run_output(self):
        task = self.make_task()
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            artifacts=[
                {"id": str(number), "name": f"artifact-{number}"} for number in range(MAX_INDEXED_ARTIFACTS + 10)
            ],
        )

        index_task_run(run.id)

        self.assertEqual(
            TaskSearchDocument.objects.for_team(self.team.id)
            .filter(kind=TaskSearchDocument.Kind.ARTIFACT, task_run_id=run.id)
            .count(),
            MAX_INDEXED_ARTIFACTS,
        )

    def test_indexes_active_living_artifact(self):
        task = self.make_task()
        run = TaskRun.objects.create(team=self.team, task=task)
        artifact = TaskArtifact.objects.for_team(self.team.id).create(
            team=self.team,
            task=task,
            task_run=run,
            created_by=self.user,
            name="Release checklist",
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            adapter=TaskArtifact.Adapter.DOCUMENT_CONNECTOR,
        )
        index_task_artifact(artifact.id)

        result = search_tasks(self.team.id, self.user.id, "release checklist")[0]
        self.assertTrue(result["metadata"]["living"])
        self.assertEqual(result["channel_id"], str(task.channel_id))

    def test_search_respects_personal_channel_visibility(self):
        personal = Channel.objects.create(
            team=self.team,
            name="me",
            channel_type=Channel.ChannelType.PERSONAL,
            created_by=self.user,
        )
        self.make_task(title="Private search target", channel=personal)
        other_user = User.objects.create(email="other@example.com", distinct_id="other-search-user")

        self.assertEqual(search_tasks(self.team.id, other_user.id, "private search target"), [])
        self.assertEqual(search_tasks(self.team.id, self.user.id, "private search target")[0]["kind"], "task")
        self.assertEqual(
            search_tasks(
                self.team.id,
                other_user.id,
                "private search target",
                bypass_visibility=True,
            )[0]["kind"],
            "task",
        )

    def test_deleted_task_descendants_are_removed(self):
        task = self.make_task()
        run = TaskRun.objects.create(
            team=self.team,
            task=task,
            output={"pr_url": "https://github.com/PostHog/posthog/pull/456"},
        )
        index_task_run(run.id)
        task.deleted = True
        task.save(update_fields=["deleted"])

        index_task_run(run.id)

        self.assertEqual(search_tasks(self.team.id, self.user.id, "456"), [])
