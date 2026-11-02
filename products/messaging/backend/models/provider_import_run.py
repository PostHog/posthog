from django.db import models
from django.db.models import Q
from django.utils.functional import Promise

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ImportProviderKey(models.TextChoices):
    CUSTOMERIO = "customerio", "Customer.io"


def import_provider_choices() -> list[tuple[str, str | Promise]]:
    # Callable so adding a provider doesn't generate a no-op migration.
    return list(ImportProviderKey.choices)


class ProviderImportStatus(models.TextChoices):
    QUEUED = "queued", "Waiting to start"
    RUNNING = "running", "Importing"
    COMPLETED = "completed", "Imported"
    FAILED = "failed", "Failed"


ACTIVE_IMPORT_STATUSES = (ProviderImportStatus.QUEUED, ProviderImportStatus.RUNNING)


class ImportStepStatus(models.TextChoices):
    PENDING = "pending", "Not started"
    RUNNING = "running", "Importing"
    COMPLETED = "completed", "Imported"
    FAILED = "failed", "Failed"


class ProviderImportRun(TeamScopedRootMixin, UUIDModel):
    """One background import of opt-outs, suppressions and other messaging data from another provider.

    The Temporal workflow runs the selected steps in order. `progress` holds the status, counts and resume point of
    each step, so a retried step continues from its last saved page and the UI can show progress.
    """

    # db_constraint=False on these hot-table FKs so CreateModel takes no lock on posthog_team / posthog_user.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, related_name="+")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    provider = models.CharField(max_length=40, choices=import_provider_choices)
    # The stored credentials the steps read. Null when someone deleted them, which fails the remaining steps.
    integration = models.ForeignKey(
        "posthog.Integration", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Step keys in the order they run.
    steps = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=ProviderImportStatus.choices, default=ProviderImportStatus.QUEUED)
    # Step key -> {"status", "processed", "imported", "warnings", "last_error", "checkpoint", "attempt"}.
    progress = models.JSONField(default=dict)

    class Meta:
        db_table = "posthog_messaging_provider_import_run"
        indexes = [models.Index(fields=["team", "-created_at"], name="pmsg_import_run_by_created")]
        constraints = [
            # Two runs against one provider would share its API rate limit and write the same rows.
            models.UniqueConstraint(
                fields=["team", "provider"],
                condition=Q(status__in=["queued", "running"]),
                name="unique_active_provider_import_run",
            ),
        ]

    def __str__(self) -> str:
        return f"ProviderImportRun {self.team_id}/{self.provider}/{self.status}"
