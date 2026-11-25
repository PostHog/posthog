import uuid

from django.conf import settings
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin


class Topic(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    title = models.CharField(max_length=255)
    mission = models.TextField()
    # Version of the Signals projection last announced to replicas. Signals owns the scout and report rows.
    scout_digest = models.CharField(max_length=64, null=True)
    chat_model = models.CharField(max_length=255, blank=True)
    state = models.JSONField(default=dict)
    revision = models.PositiveBigIntegerField(default=1)
    archived = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    conversation_id = models.UUIDField(null=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class CommandReceipt(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="receipts")
    command_id = models.UUIDField()
    revision = models.PositiveBigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["topic", "command_id"], name="meep_unique_topic_command")]


class ChatTurn(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="turns")
    message_id = models.UUIDField()
    text = models.TextField()
    run_id = models.UUIDField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    reply = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["topic", "message_id"], name="meep_unique_topic_message")]


class WorkspaceView(TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    id = models.UUIDField(primary_key=True)
    state = models.JSONField(default=dict)


class ViewReceipt(models.Model):
    view = models.ForeignKey(WorkspaceView, on_delete=models.CASCADE)
    command_id = models.UUIDField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["view", "command_id"], name="meep_unique_view_command")]


class DeletionReceipt(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE)
    replica = models.UUIDField()
    revision = models.PositiveBigIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["topic", "replica"], name="meep_unique_deletion_receipt")]


class FileRevision(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="files")
    path = models.TextField()
    revision = models.PositiveBigIntegerField()
    operation = models.UUIDField()
    base = models.PositiveBigIntegerField(null=True)
    competing_with = models.PositiveBigIntegerField(null=True)
    contents = models.BinaryField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["topic", "path", "revision"], name="meep_unique_file_revision"),
            models.UniqueConstraint(fields=["topic", "path", "operation"], name="meep_unique_file_operation"),
        ]


class ViewJob(models.Model):
    view = models.ForeignKey(WorkspaceView, on_delete=models.CASCADE, related_name="jobs")
    turn_id = models.UUIDField(unique=True)
    session = models.UUIDField()
    task_id = models.UUIDField()
    run_id = models.UUIDField(unique=True)
    generation = models.PositiveBigIntegerField()
    finished = models.BooleanField(default=False)


class BoardRun(models.Model):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name="board_runs")
    item_id = models.UUIDField()
    task_id = models.UUIDField()
    run_id = models.UUIDField(unique=True)
    finished = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["topic", "item_id"], condition=models.Q(finished=False), name="meep_one_live_board_run"
            )
        ]
