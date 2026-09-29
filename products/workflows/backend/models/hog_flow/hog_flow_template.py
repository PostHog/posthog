from typing import TYPE_CHECKING

from django.contrib.postgres.fields import ArrayField
from django.db import models

import structlog

from posthog.models.utils import UUIDTModel

from products.workflows.backend.facade.enums import HogFlowTemplateExitCondition, HogFlowTemplateScope

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class HogFlowTemplate(UUIDTModel):
    """
    Stores workflow templates that can be used to create new workflows.
    """

    class Meta:
        db_table = "hogflow_templates"
        indexes = [
            models.Index(fields=["team"]),
        ]

    ExitCondition = HogFlowTemplateExitCondition
    Scope = HogFlowTemplateScope

    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    image_url = models.CharField(max_length=8201, null=True, blank=True)
    tags = ArrayField(models.CharField(max_length=255), blank=True, default=list)
    scope = models.CharField(max_length=24, choices=Scope)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    trigger = models.JSONField(default=dict)
    trigger_masking = models.JSONField(null=True, blank=True)
    conversion = models.JSONField(null=True, blank=True)
    exit_condition = models.CharField(max_length=100, choices=ExitCondition, default=ExitCondition.CONVERSION)

    edges = models.JSONField(default=dict)
    actions = models.JSONField(default=dict)
    abort_action = models.CharField(max_length=400, null=True, blank=True)
    variables = models.JSONField(default=list, null=True, blank=True)

    def __str__(self):
        return f"HogFlowTemplate {self.id}: {self.name}"
