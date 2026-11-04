from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.workflows.backend.facade.enums import PushTokenImportStatus


class PushTokenImport(TeamScopedRootMixin, UUIDModel):
    """One uploaded file of device tokens, imported into a push channel in the background."""

    Status = PushTokenImportStatus

    class Meta:
        indexes = [models.Index(fields=["team", "integration_id", "-created_at"], name="push_token_import_channel_idx")]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "integration_id"],
                condition=models.Q(status="running"),
                name="push_token_import_one_running",
            )
        ]

    # db_constraint=False: a real FK constraint to a hot table takes a parent-table lock on creation.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    # Integration rows are read through the integrations SDK, which hands out ids, not model instances.
    integration_id = models.BigIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RUNNING.value)
    create_missing_persons = models.BooleanField(default=False)
    total_devices = models.PositiveIntegerField(default=0)
    processed_devices = models.PositiveIntegerField(default=0)
    imported_devices = models.PositiveIntegerField(default=0)
    failed_devices = models.PositiveIntegerField(default=0)
    duplicate_lines = models.PositiveIntegerField(default=0)
    failures = models.JSONField(
        default=list,
        blank=True,
        help_text="The first failed lines: a list of {line, distinct_id, device_token_suffix, reason, detail}.",
    )
    unknown_person_lines = models.JSONField(
        default=list,
        blank=True,
        help_text="Every line whose distinct ID had no person, so those devices can be imported again.",
    )
    error = models.TextField(blank=True, default="")
    # Times the stall check queued the task again after a worker stopped mid-import.
    resumed_times = models.PositiveSmallIntegerField(default=0)
    # The encrypted devices in object storage. Cleared once nothing can read them again.
    storage_key = models.CharField(max_length=400, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )

    def __str__(self) -> str:
        return f"PushTokenImport {self.team_id}/{self.integration_id}/{self.id}"
