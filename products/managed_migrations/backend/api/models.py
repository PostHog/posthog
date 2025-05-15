from django.db import models
from posthog.models import Team, User
from posthog.models.utils import UUIDModel


class ManagedMigration(UUIDModel):
    """A model representing a data migration from another analytics provider."""

    class Status(models.TextChoices):
        """Possible states of the ManagedMigration."""

        CANCELLED = "Cancelled"
        COMPLETED = "Completed"
        FAILED = "Failed"
        RUNNING = "Running"
        STARTING = "Starting"

    class Source(models.TextChoices):
        """Supported data sources for migration."""

        AMPLITUDE = "amplitude"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, help_text="The team this migration belongs to.")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, help_text="The user who created this migration."
    )
    source = models.CharField(choices=Source.choices, max_length=64, help_text="The source of the data.")
    api_key = models.TextField(help_text="API key for the source.")
    secret_key = models.TextField(help_text="Secret key for the source.")
    start_date = models.DateTimeField(help_text="Start date for the data migration.")
    end_date = models.DateTimeField(help_text="End date for the data migration.")
    event_names_mode = models.CharField(
        max_length=64,
        choices=[
            ("all", "Import all events"),
            ("allow", "Only import these events"),
            ("deny", "Don't import these events"),
        ],
        help_text="Mode for filtering event names.",
    )
    event_names = models.JSONField(
        null=True,
        blank=True,
        help_text="List of event names to include or exclude based on event_names_mode.",
    )
    status = models.CharField(
        choices=Status.choices,
        max_length=64,
        default=Status.STARTING,
        help_text="Current status of the migration.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The timestamp at which this migration was created.",
    )
    finished_at = models.DateTimeField(
        null=True,
        help_text="The timestamp at which this migration finished, successfully or not.",
    )
    last_updated_at = models.DateTimeField(
        auto_now=True,
        help_text="The timestamp at which this migration was last updated.",
    )
    error = models.TextField(
        null=True,
        blank=True,
        help_text="Error message if the migration failed.",
    )
    workflow_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="ID of the Temporal workflow handling this migration.",
    )
