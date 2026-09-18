"""
Django models for wizard.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel

from products.wizard.backend.facade.enums import (
    WizardRunArtifactType,
    WizardRunDispatchStatus,
    WizardRunEnvironment,
    WizardRunStage,
    WizardRunStatus,
    WizardSessionRunPhase,
    WizardWorkerCleanupStatus,
    WizardWorkspaceType,
)


class WizardSession(UUIDModel, TeamScopedRootMixin, CreatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")

    # db_constraint=False because posthog_user is a hot table (a constrained FK would lock it).
    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )

    session_id = models.CharField(max_length=255)
    workflow_id = models.CharField(max_length=255)
    skill_id = models.CharField(max_length=255)
    started_at = models.DateTimeField()

    run_phase = models.CharField(max_length=50, choices=[(phase.value, phase.value) for phase in WizardSessionRunPhase])

    tasks = models.JSONField(default=list)
    event_plan = models.JSONField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)
    # An in-flight wizard_ask prompt ({id, asked_at, question_count, sensitive, prompts?}).
    # Null means no input is pending — each push replaces it, so the CLI clearing the
    # question is just the next upsert without the field.
    pending_input = models.JSONField(null=True, blank=True)
    # The markdown handoff doc (the wizard's setup report) once the run has produced one.
    # Unlike the fields above it is monotonic within a session: a push without it keeps
    # the stored value (see upsert_session), since the doc arrives late in the run.
    handoff_text = models.TextField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["team", "session_id"], name="unique_wizard_session_per_team")]

        indexes = [
            # to optimize fetching the latest session
            models.Index(
                fields=["team", "workflow_id", "skill_id", "-started_at"],
            ),
            # the detector queries team + workflow_id (no skill_id) ordered by started_at desc
            models.Index(
                fields=["team", "workflow_id", "-started_at"],
                name="wizard_sess_team_wf_start_idx",
            ),
        ]


class WizardRun(UUIDModel, TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    created_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        db_constraint=False,
    )

    environment = models.CharField(
        max_length=20,
        choices=[(environment.value, environment.value) for environment in WizardRunEnvironment],
    )

    workspace_type = models.CharField(
        max_length=30,
        choices=[(workspace_type.value, workspace_type.value) for workspace_type in WizardWorkspaceType],
    )

    workspace = models.JSONField()

    program = models.JSONField()

    status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in WizardRunStatus],
    )

    error_code = models.CharField(max_length=50, null=True, blank=True)

    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    request_fingerprint = models.CharField(max_length=64, null=True, blank=True)

    dispatch_status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in WizardRunDispatchStatus],
        null=True,
        blank=True,
    )
    dispatch_attempts = models.PositiveSmallIntegerField(default=0)
    dispatch_error = models.CharField(max_length=255, null=True, blank=True)
    dispatch_next_attempt_at = models.DateTimeField(null=True, blank=True)
    workflow_id = models.CharField(max_length=255, null=True, blank=True)

    stage = models.CharField(
        max_length=30,
        choices=[(stage.value, stage.value) for stage in WizardRunStage],
        null=True,
        blank=True,
    )
    stage_started_at = models.DateTimeField(null=True, blank=True)
    error_message = models.CharField(max_length=255, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    deadline_at = models.DateTimeField(null=True, blank=True)
    cancellation_requested_at = models.DateTimeField(null=True, blank=True)
    cancellation_dispatched_at = models.DateTimeField(null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["team", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="unique_wizard_run_idempotency_key_per_team",
            )
        ]
        indexes = [
            models.Index(
                fields=["dispatch_next_attempt_at", "created_at"],
                condition=models.Q(status="created", dispatch_status="pending"),
                name="wizard_run_dispatch_idx",
            ),
            models.Index(
                fields=["id"],
                condition=models.Q(
                    status__in=("cancelled", "failed"),
                    cancellation_requested_at__isnull=False,
                    cancellation_dispatched_at__isnull=True,
                ),
                name="wizard_run_cancel_idx",
            ),
            models.Index(
                fields=["deadline_at"],
                condition=models.Q(status__in=("created", "running"), deadline_at__isnull=False),
                name="wizard_run_deadline_idx",
            ),
        ]


class WizardRunArtifact(UUIDModel, TeamScopedRootMixin):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    run = models.ForeignKey(WizardRun, on_delete=models.CASCADE, related_name="artifacts")
    type = models.CharField(
        max_length=30,
        choices=[(artifact_type.value, artifact_type.value) for artifact_type in WizardRunArtifactType],
    )
    storage_path = models.CharField(max_length=1024, null=True, blank=True)
    external_url = models.URLField(max_length=1024, null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)
    size_bytes = models.PositiveBigIntegerField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(TeamScopedRootMixin.Meta):
        constraints = [models.UniqueConstraint(fields=["run", "type"], name="unique_wizard_artifact_type_per_run")]


# This tracks provisioned Wizard Workers, helping monitor resource
# usage, and handle provisioning-related errors.
class WizardWorker(UUIDModel, TeamScopedRootMixin, UpdatedMetaFields):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    run = models.OneToOneField(WizardRun, on_delete=models.CASCADE, related_name="worker")

    created_at = models.DateTimeField(auto_now_add=True)

    sandbox_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    resource_usage = models.JSONField(null=True, blank=True)

    cleanup_status = models.CharField(
        max_length=20,
        choices=[(status.value, status.value) for status in WizardWorkerCleanupStatus],
        default=WizardWorkerCleanupStatus.ACTIVE.value,
    )
    cleanup_attempts = models.PositiveSmallIntegerField(default=0)
    cleanup_error = models.CharField(max_length=255, null=True, blank=True)
    cleaned_at = models.DateTimeField(null=True, blank=True)

    class Meta(TeamScopedRootMixin.Meta):
        indexes = [
            models.Index(
                fields=["cleanup_attempts"],
                condition=models.Q(cleanup_status__in=("active", "pending"), sandbox_id__isnull=False),
                name="wizard_worker_cleanup_idx",
            )
        ]
