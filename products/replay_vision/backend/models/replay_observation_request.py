from django.contrib.postgres.fields import ArrayField
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ObservationRequestSource(models.TextChoices):
    USER = "user", "User"
    PROJECT_SECRET_API_KEY = "project_secret_api_key", "Project secret API key"
    WORKFLOW = "workflow", "Workflow"


class ReplayObservationRequest(TeamScopedRootMixin, UUIDModel):
    """One programmatic ask to scan named sessions, read back through one handle.

    The observations stay keyed by (scanner, session), so a request holds no results of its own: it
    records which sessions it asked for and what happened when each one started.
    """

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    # SET_NULL because an inline scanner that started nothing is never minted, and one that ends up with no
    # observations is reaped; the request must outlive both so the caller still sees why nothing ran.
    scanner = models.ForeignKey(
        "replay_vision.ReplayScanner",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    session_ids = ArrayField(models.CharField(max_length=200), help_text="Session recording ids, in request order.")
    start_outcomes = models.JSONField(
        help_text="Per-session `{session_id, scan_outcome}` from the moment the request started, in request order."
    )
    idempotency_key = models.CharField(max_length=200, null=True, blank=True)
    reference = models.CharField(
        max_length=200, blank=True, default="", help_text="Caller-supplied correlation id, echoed back unchanged."
    )
    source = models.CharField(max_length=32, choices=ObservationRequestSource.choices)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    wait_for_session_end = models.BooleanField(
        default=False, help_text="Hold the scans until every session has ended, so each one is scanned whole."
    )
    inline_config = models.JSONField(
        null=True,
        blank=True,
        help_text="The inline question's `{scanner_type, scanner_config, model}`, kept until a waiting request starts.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="rvor_team_idempotency_key_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["team", "created_at"], name="rvor_team_created_idx"),
            models.Index(
                fields=["created_at"], name="rvor_open_created_idx", condition=models.Q(completed_at__isnull=True)
            ),
        ]

    def __str__(self) -> str:
        return f"{self.id} [{len(self.session_ids)} sessions]"
