import uuid

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel


class Execution(ProductTeamModel):
    execution_id = models.TextField(db_index=True)
    run_id = models.UUIDField(default=uuid.uuid4)
    execution_type = models.TextField()
    step_queue = models.TextField(default="default")
    input = models.JSONField(null=True)
    status = models.TextField(default="RUNNING")
    result = models.JSONField(null=True)
    error = models.JSONField(null=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "orchestra"
        unique_together = [("execution_id", "run_id")]
        default_manager_name = "all_teams"


class Event(models.Model):
    execution_id = models.TextField(primary_key=True)
    run_id = models.UUIDField()
    event_id = models.BigIntegerField()
    event_type = models.TextField()
    team_id = models.BigIntegerField(db_index=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    attributes = models.JSONField(default=dict)

    class Meta:
        managed = False
        db_table = "orchestra_event"
        app_label = "orchestra"


class Task(ProductTeamModel):
    task_id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    task_queue = models.TextField()
    task_type = models.TextField()
    execution_id = models.TextField()
    run_id = models.UUIDField()
    scheduled_event_id = models.BigIntegerField(null=True)
    step_type = models.TextField(null=True)
    input = models.JSONField(null=True)
    visible_at = models.DateTimeField(auto_now_add=True)
    locked_by = models.TextField(null=True)
    locked_until = models.DateTimeField(null=True)
    attempt = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "orchestra"
        default_manager_name = "all_teams"
        indexes = [
            models.Index(
                fields=["task_queue", "visible_at"],
                name="idx_orch_tasks_poll",
                condition=models.Q(locked_until__isnull=True),
            ),
            models.Index(
                fields=["task_queue", "locked_until"],
                name="idx_orch_tasks_lease",
                condition=models.Q(locked_until__isnull=False),
            ),
        ]
