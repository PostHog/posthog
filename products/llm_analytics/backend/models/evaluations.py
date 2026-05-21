from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from posthog.models.utils import UUIDTModel

from .evaluation_configs import EvaluationType, OutputType, validate_evaluation_configs

logger = structlog.get_logger(__name__)


class EvaluationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PAUSED = "paused", "Paused"
    ERROR = "error", "Error"


class EvaluationStatusReason(models.TextChoices):
    TRIAL_LIMIT_REACHED = "trial_limit_reached", "Trial evaluation limit reached"
    MODEL_NOT_ALLOWED = "model_not_allowed", "Model not available on the trial plan"
    PROVIDER_KEY_DELETED = "provider_key_deleted", "Provider API key was deleted"


class Evaluation(UUIDTModel):
    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "-created_at", "id"]),
            models.Index(fields=["team", "enabled"]),
            models.Index(fields=["model_configuration"], name="llm_analyti_model_c_idx"),
        ]

    # Core fields
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")

    # Lifecycle state. `status` is authoritative; `enabled` is a boolean projection kept in sync by save() for
    # backwards compatibility with existing API / DB callers. When status is ERROR, status_reason must be set.
    enabled = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=EvaluationStatus, default=EvaluationStatus.PAUSED)
    status_reason = models.CharField(max_length=50, choices=EvaluationStatusReason, null=True, blank=True)

    evaluation_type = models.CharField(max_length=50, choices=EvaluationType)
    evaluation_config = models.JSONField(default=dict)
    output_type = models.CharField(max_length=50, choices=OutputType)
    output_config = models.JSONField(default=dict)

    conditions = models.JSONField(default=list)

    # Model configuration for the LLM judge
    model_configuration = models.ForeignKey(
        "llm_analytics.LLMModelConfiguration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluations",
        db_index=False,
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Snapshot of the fields as last loaded / saved — used by _coerce_status_and_enabled to know which
        # field the caller actually moved when enabled and status disagree.
        self._initial_enabled = self.enabled
        self._initial_status = self.status

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._initial_enabled = instance.enabled
        instance._initial_status = instance.status
        return instance

    def refresh_from_db(self, *args, **kwargs) -> None:
        # Refreshing replaces the in-memory state with DB state — the change-tracking baseline must
        # follow, otherwise a subsequent caller-side edit would be compared against stale initials and
        # the coerce step could misinterpret which field moved.
        super().refresh_from_db(*args, **kwargs)
        self._initial_enabled = self.enabled
        self._initial_status = self.status

    def __str__(self):
        return self.name

    def _coerce_status_and_enabled(self) -> None:
        """Reconcile status with enabled at save time.

        New records: derive status from enabled unless the caller explicitly set status (e.g. ERROR + reason).
        Existing records: whichever field actually changed since load drives the other. This lets existing
        callers keep PATCHing `enabled` without knowing about status, while system transitions that write
        `status` directly take effect even when `enabled` is stale in memory.

        Post-reconciliation invariants are always enforced:
            - ACTIVE  → enabled=True,  status_reason=None
            - PAUSED  → enabled=False, status_reason=None
            - ERROR   → enabled=False, status_reason required (raises otherwise)
        """
        # UUIDTModel assigns pk in __init__, so we can't use `self.pk is None` to detect new rows.
        is_new = self._state.adding
        if is_new:
            if self.status == EvaluationStatus.PAUSED and self.enabled:
                self.status = EvaluationStatus.ACTIVE
            elif self.status == EvaluationStatus.ACTIVE and not self.enabled:
                self.status = EvaluationStatus.PAUSED
        else:
            enabled_changed = self.enabled != self._initial_enabled
            status_changed = self.status != self._initial_status
            if status_changed and not enabled_changed:
                self.enabled = self.status == EvaluationStatus.ACTIVE
            elif enabled_changed and not status_changed:
                self.status = EvaluationStatus.ACTIVE if self.enabled else EvaluationStatus.PAUSED

        if self.status == EvaluationStatus.ACTIVE:
            self.enabled = True
            self.status_reason = None
        elif self.status == EvaluationStatus.PAUSED:
            self.enabled = False
            self.status_reason = None
        elif self.status == EvaluationStatus.ERROR:
            self.enabled = False
            if not self.status_reason:
                raise ValidationError({"status_reason": "status_reason is required when status is ERROR"})

    def set_status(
        self, status: "EvaluationStatus | str", reason: "EvaluationStatusReason | str | None" = None
    ) -> None:
        """Transition helper. Prefer this (or .save()) over .update() so invariants stay enforced.

        Callers using QuerySet.update() bypass save() — they must write all three fields together.
        """
        self.status = EvaluationStatus(status)
        self.status_reason = EvaluationStatusReason(reason) if reason else None
        self.save(update_fields=["status", "status_reason", "enabled", "updated_at"])

    def save(self, *args, **kwargs):
        from posthog.cdp.filters import compile_filters_bytecode
        from posthog.cdp.validation import compile_hog

        # Coerce status and enabled into a consistent pair. status is authoritative, but we accept writes to
        # either field — typically `enabled` from user PATCHes, `status` from system transitions.
        self._coerce_status_and_enabled()

        # Validate evaluation and output configs
        if self.evaluation_config or self.output_config:
            try:
                self.evaluation_config, self.output_config = validate_evaluation_configs(
                    self.evaluation_type, self.output_type, self.evaluation_config, self.output_config
                )
            except ValueError as e:
                raise ValidationError(str(e))

        # Compile Hog source to bytecode
        if self.evaluation_type == EvaluationType.HOG and self.evaluation_config.get("source"):
            try:
                bytecode = compile_hog(self.evaluation_config["source"], "destination")
                self.evaluation_config["bytecode"] = bytecode
            except Exception as e:
                raise ValidationError({"evaluation_config": f"Failed to compile Hog code: {e}"})

        # Compile bytecode for each condition
        compiled_conditions = []
        for condition in self.conditions:
            compiled_condition = {**condition}
            filters = {"properties": condition.get("properties", [])}
            compiled = compile_filters_bytecode(filters, self.team)
            compiled_condition["bytecode"] = compiled.get("bytecode")
            compiled_condition["bytecode_error"] = compiled.get("bytecode_error")
            compiled_conditions.append(compiled_condition)

        self.conditions = compiled_conditions
        result = super().save(*args, **kwargs)
        # Refresh the baseline so the next save cycle compares against the post-save state.
        self._initial_enabled = self.enabled
        self._initial_status = self.status
        return result


@receiver(post_save, sender=Evaluation)
def evaluation_saved(sender, instance, created, **kwargs):
    from posthog.plugins.plugin_server_api import reload_evaluations_on_workers

    # Defer publishing to workers until the surrounding transaction commits — otherwise
    # workers can fire before the row is visible, especially now that perform_create wraps
    # the save + EvaluationReport create in transaction.atomic(). In auto-commit mode
    # on_commit fires synchronously, preserving prior behavior.
    team_id = instance.team_id
    evaluation_id = str(instance.id)
    transaction.on_commit(lambda: reload_evaluations_on_workers(team_id=team_id, evaluation_ids=[evaluation_id]))
