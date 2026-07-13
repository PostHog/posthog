from typing import TYPE_CHECKING, Final

from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver

import structlog

from posthog.models.team.team import Team
from posthog.models.utils import UUIDTModel
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers

from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# Billable action types that are subject to rate limiting and quota tracking
# These action types incur costs and are counted against customer quotas
BILLABLE_ACTION_TYPES: Final[set[str]] = {
    "function",  # General function/webhook actions
    "function_email",  # Email sending actions
    "function_sms",  # SMS sending actions
    "function_push",  # Push notification actions
}

# Action types that read person data and therefore cannot be used in person-less ("row-scoped")
# workflows such as those triggered by a data warehouse table row sync. Keep in sync with the
# frontend's PERSON_DEPENDENT_ACTION_TYPES.
PERSON_DEPENDENT_ACTION_TYPES: Final[set[str]] = {
    "wait_until_condition",
    "random_cohort_branch",
}


class HogFlow(UUIDTModel):
    """
    Stores the version, layout and other meta information for each HogFlow
    """

    class Meta:
        db_table = "posthog_hogflow"
        indexes = [
            models.Index(fields=["status", "team"]),
            models.Index(fields=["version", "team"]),
        ]

        constraints = [
            models.UniqueConstraint(fields=["team", "version", "id"], name="unique_version_per_flow"),
        ]

    class State(models.TextChoices):
        DRAFT = "draft"
        ACTIVE = "active"
        ARCHIVED = "archived"

    class ExitCondition(models.TextChoices):
        CONVERSION = "exit_on_conversion"
        TRIGGER_NOT_MATCHED = "exit_on_trigger_not_matched"
        TRIGGER_NOT_MATCHED_OR_CONVERSION = "exit_on_trigger_not_matched_or_conversion"
        ONLY_AT_END = "exit_only_at_end"

    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    version = models.IntegerField(default=1)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=State, default=State.DRAFT)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    trigger = models.JSONField(default=dict)
    trigger_masking = models.JSONField(null=True, blank=True)
    conversion = models.JSONField(null=True, blank=True)
    exit_condition = models.CharField(max_length=100, choices=ExitCondition, default=ExitCondition.CONVERSION)

    edges = models.JSONField(default=dict)
    actions = models.JSONField(default=dict)
    abort_action = models.CharField(max_length=400, null=True, blank=True)
    variables = models.JSONField(default=list, null=True, blank=True)

    # Pre-computed set of billable action types in this workflow for efficient quota checking
    # Contains only billable action types: 'function', 'function_email', 'function_sms', 'function_push'
    billable_action_types = models.JSONField(default=list, null=True, blank=True)

    # Draft storage for active workflows: stores pending edits separately from live config
    draft = models.JSONField(null=True, blank=True)
    draft_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"HogFlow {self.id}/{self.version}: {self.name}"


class HogFlowIntegration(models.Model):
    """Join row recording that a hog flow's live action config references an integration.

    Derived from the flow's JSON actions (which stay the runtime source of truth) and kept
    in sync on save — see products/workflows/backend/services/integration_usage.py. Exists so
    reverse lookups ("what uses this integration?") don't need to scan JSON blobs.
    """

    id = models.BigAutoField(primary_key=True)
    hog_flow = models.ForeignKey("workflows.HogFlow", on_delete=models.CASCADE, related_name="integration_links")
    integration = models.ForeignKey("posthog.Integration", on_delete=models.CASCADE, related_name="hog_flow_links")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["hog_flow", "integration"], name="unique_hog_flow_integration"),
        ]

    def __str__(self):
        return f"HogFlowIntegration {self.hog_flow_id} -> {self.integration_id}"


@receiver(post_save, sender=HogFlow)
def hog_flow_saved(sender, instance: HogFlow, created, **kwargs):
    reload_hog_flows_on_workers(team_id=instance.team_id, hog_flow_ids=[str(instance.id)])


@receiver(post_save, sender=HogFlow)
def hog_flow_integration_links_synced(sender, instance: HogFlow, created, **kwargs):
    # The service imports this module's models — import at call time to break the cycle.
    from products.workflows.backend.services.integration_usage import sync_hog_flow_integrations  # noqa: PLC0415

    sync_hog_flow_integrations(instance)


@receiver(post_delete, sender=HogFlow)
def hog_flow_deleted(sender, instance: HogFlow, **kwargs):
    team_id = instance.team_id
    hog_flow_id = str(instance.id)
    # post_delete fires inside the delete transaction, so publish only after commit; otherwise a
    # worker could re-read the still-live row and cache it as active for another TTL.
    transaction.on_commit(lambda: reload_hog_flows_on_workers(team_id=team_id, hog_flow_ids=[hog_flow_id]))


@receiver(post_save, sender=Action)
def action_saved_for_hog_flows(sender, instance: Action, created, **kwargs):
    from products.workflows.backend.tasks.hog_flows import refresh_affected_hog_flows  # noqa: PLC0415

    refresh_affected_hog_flows.delay(action_id=instance.id)


@receiver(post_save, sender=Team)
def team_saved_for_hog_flows(sender, instance: Team, created, **kwargs):
    from products.workflows.backend.tasks.hog_flows import refresh_affected_hog_flows  # noqa: PLC0415

    refresh_affected_hog_flows.delay(team_id=instance.id)
