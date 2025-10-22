from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.utils import UUIDTModel

from .evaluation_configs import EvaluationType, OutputType, validate_evaluation_configs


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
        if self.evaluation_config or self.output_config:
            try:
                self.evaluation_config, self.output_config = validate_evaluation_configs(
                    self.evaluation_type, self.output_type, self.evaluation_config, self.output_config
                )
            except ValueError as e:
                raise ValidationError(str(e))

        return super().save(*args, **kwargs)
