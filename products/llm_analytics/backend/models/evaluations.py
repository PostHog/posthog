from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from posthog.models.utils import UUIDTModel

from .evaluation_configs import EvaluationType, OutputType, validate_evaluation_configs

logger = structlog.get_logger(__name__)


class Evaluation(UUIDTModel):
    class Meta:
        ordering = ["-created_at", "id"]
        indexes = [
            models.Index(fields=["team", "-created_at", "id"]),
            models.Index(fields=["team", "enabled"]),
        ]

    # Core fields
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=False)

    evaluation_type = models.CharField(max_length=50, choices=EvaluationType.choices)
    evaluation_config = models.JSONField(default=dict)
    output_type = models.CharField(max_length=50, choices=OutputType.choices)
    output_config = models.JSONField(default=dict)

    conditions = models.JSONField(default=list)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    deleted = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        from posthog.cdp.filters import compile_filters_bytecode

        # Validate evaluation and output configs
        if self.evaluation_config or self.output_config:
            try:
                self.evaluation_config, self.output_config = validate_evaluation_configs(
                    self.evaluation_type, self.output_type, self.evaluation_config, self.output_config
                )
            except ValueError as e:
                raise ValidationError(str(e))

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
        return super().save(*args, **kwargs)


@receiver(post_save, sender=Evaluation)
def evaluation_saved(sender, instance, created, **kwargs):
    from posthog.plugins.plugin_server_api import reload_evaluations_on_workers

    reload_evaluations_on_workers(team_id=instance.team_id, evaluation_ids=[str(instance.id)])
