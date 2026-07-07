from typing import Any

from posthog.test.base import TestMigrations


class BackfillThreadMessageMentionsMigrationTest(TestMigrations):
    """0050 indexes mentions already stored inline in existing thread messages. The backfill
    must mirror write-time extraction: org members only, self-mentions skipped, created_at
    copied from the message.
    """

    migrate_from = "0049_taskthreadmessagemention"
    migrate_to = "0050_backfill_thread_message_mentions"

    @property
    def app(self) -> str:
        return "tasks"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        OrganizationMembership = apps.get_model("posthog", "OrganizationMembership")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        User = apps.get_model("posthog", "User")
        Task = apps.get_model("tasks", "Task")
        TaskThreadMessage = apps.get_model("tasks", "TaskThreadMessage")

        org = Organization.objects.create(name="Org")
        project = Project.objects.create(id=999_999, organization=org, name="Proj")
        team = Team.objects.create(organization=org, project=project, name="Team")
        author = User.objects.create(email="author@example.com", distinct_id="author-distinct")
        peer = User.objects.create(email="peer@example.com", distinct_id="peer-distinct")
        for user in (author, peer):
            OrganizationMembership.objects.create(organization=org, user=user)

        task = Task.objects.create(team=team, title="T", description="d", origin_product="user_created")
        self.peer_id = peer.id
        self.mention_message_id = TaskThreadMessage.objects.create(
            team=team, task=task, author=author, content="hey @[Bob](Peer@Example.com)"
        ).id
        # Self-mention and non-member mention must not produce rows.
        TaskThreadMessage.objects.create(team=team, task=task, author=author, content="me @[Ann](author@example.com)")
        TaskThreadMessage.objects.create(team=team, task=task, author=author, content="cc @[Sam](sam@elsewhere.com)")

    def test_backfills_org_member_mentions_only(self) -> None:
        TaskThreadMessage = self.apps.get_model("tasks", "TaskThreadMessage")  # type: ignore[union-attr]
        TaskThreadMessageMention = self.apps.get_model("tasks", "TaskThreadMessageMention")  # type: ignore[union-attr]

        mentions = list(TaskThreadMessageMention.objects.all())
        assert len(mentions) == 1
        assert mentions[0].message_id == self.mention_message_id
        assert mentions[0].mentioned_user_id == self.peer_id
        assert mentions[0].created_at == TaskThreadMessage.objects.get(id=self.mention_message_id).created_at
