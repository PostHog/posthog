from typing import TYPE_CHECKING, Final

from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver

import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.team.team import Team
from posthog.models.utils import UUIDTModel
from posthog.plugins.plugin_server_api import reload_hog_flows_on_workers

from products.actions.backend.models.action import Action

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

# Every action type the worker can execute. Must stay in sync with the `actionHandlers` registry in
# nodejs/src/cdp/services/hogflows/hogflow-executor.service.ts (and the schemas mirroring it in
# nodejs/src/cdp/schema/hogflow.ts and products/workflows/frontend/Workflows/hogflows/steps/types.ts).
# A type absent here has no handler, so the run dies on reaching it with "Action type 'x' not
# supported" - and unless that step sets on_error: continue, everything downstream never happens.
# Ordered longest-lived first so the generated API/MCP enum reads in a sensible order.
SUPPORTED_ACTION_TYPES: Final[list[str]] = [
    "trigger",
    "function",
    "function_email",
    "function_sms",
    "function_push",
    "delay",
    "wait_until_condition",
    "wait_until_time_window",
    "conditional_branch",
    "random_cohort_branch",
    "exit",
]

# The trigger's own kinds, which live in the workflow's `trigger` field rather than on an action.
# Callers confuse the two (a stored workflow had an action of type "webhook", which is a trigger
# kind), so the rejection message can say which mistake was made. Mirrors HogFlowTriggerSchema in
# nodejs/src/cdp/schema/hogflow.ts.
TRIGGER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "event",
        "schedule",
        "manual",
        "batch",
        "tracking_pixel",
        "webhook",
        "data-warehouse-table",
        "data-warehouse-view",
        "slack-message",
    }
)

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

# Trigger types that start a run with no person attached: a synced warehouse row and a Slack message
# are both authored by something PostHog has no person record for. Keep in sync with the frontend's
# ROW_SCOPED_TRIGGER_TYPES.
ROW_SCOPED_TRIGGER_TYPES: Final[set[str]] = {
    "data-warehouse-table",
    "data-warehouse-view",
    "slack-message",
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

    # Optional email pacing for deliverability: {"count": <int>, "period": "minute" | "hour"}.
    # Enforced per workflow by the email worker, which spreads sends instead of dropping them.
    email_sending_rate_limit = models.JSONField(null=True, blank=True)

    edges = models.JSONField(default=dict)
    actions = models.JSONField(default=dict)
    # Secret function inputs (schema fields marked secret, e.g. API keys / auth headers) split out of
    # `actions` and stored Fernet-encrypted at rest, keyed by action id then input key. Keeps plaintext
    # secrets out of `actions`, `draft`, revision snapshots, and activity-log diffs. Mirrors
    # HogFunction.encrypted_inputs; the worker decrypts and merges these back before execution.
    encrypted_inputs: EncryptedJSONStringField = EncryptedJSONStringField(null=True, blank=True)
    abort_action = models.CharField(max_length=400, null=True, blank=True)
    variables = models.JSONField(default=list, null=True, blank=True)

    # Pre-computed set of billable action types in this workflow for efficient quota checking
    # Contains only billable action types: 'function', 'function_email', 'function_sms', 'function_push'
    billable_action_types = models.JSONField(default=list, null=True, blank=True)

    # Draft storage for active workflows: stores pending edits separately from live config
    draft = models.JSONField(null=True, blank=True)
    draft_updated_at = models.DateTimeField(null=True, blank=True)
    # Pending secret function inputs for the draft, same shape as `encrypted_inputs`. Kept separate so
    # a draft's secrets are promoted to `encrypted_inputs` on publish and dropped on discard, without
    # touching the live values.
    draft_encrypted_inputs: EncryptedJSONStringField = EncryptedJSONStringField(null=True, blank=True)

    # Skip-forward map for deleted steps: {deleted_action_id: next surviving action_id}. Maintained
    # by the API whenever a live graph edit deletes actions, so runs parked on a deleted step can
    # continue at its surviving successor instead of exiting. Values always reference actions
    # present in this row's `actions`; entries with no surviving successor are omitted.
    action_redirects = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"HogFlow {self.id}/{self.version}: {self.name}"


@receiver(post_save, sender=HogFlow)
def hog_flow_saved(sender, instance: HogFlow, created, update_fields=None, **kwargs):
    # Draft columns don't affect live execution, so workers don't need a config reload for them.
    if update_fields and set(update_fields) <= {"draft", "draft_updated_at"}:
        return
    reload_hog_flows_on_workers(team_id=instance.team_id, hog_flow_ids=[str(instance.id)])


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
