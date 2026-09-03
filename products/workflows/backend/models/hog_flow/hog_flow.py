from typing import TYPE_CHECKING, Final

from django.db import models, transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch.dispatcher import receiver
from django.utils.functional import Promise

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
        "internal-event",
    }
)

# The internal events a workflow may subscribe to. The internal-events stream carries payloads
# that each owning product gates behind its own scopes — recording content, exception detail,
# activity detail, alert bodies — while starting a workflow needs only hog_flow:write. An
# allowlist keeps that gap closed by default, so adding a trigger means answering the
# authorization question for that event. Pair a new entry with a tile in
# products/workflows/frontend/Workflows/hogflows/registry/triggers/.
WORKFLOW_SAFE_INTERNAL_EVENTS: Final[frozenset[str]] = frozenset({"$slack_message_received", "$github_event_received"})

# Billable action types that are subject to rate limiting and quota tracking
# These action types incur costs and are counted against customer quotas
BILLABLE_ACTION_TYPES: Final[set[str]] = {
    "function",  # General function/webhook actions
    "function_email",  # Email sending actions
    "function_sms",  # SMS sending actions
    "function_push",  # Push notification actions
}

# Action types that send a message to a person. A workflow containing at least one of these is a
# "messaging" workflow; everything else is an "automation". Keep in sync with the frontend's
# WorkflowTypeTag (products/workflows/frontend/Workflows/WorkflowsTable.tsx), which renders the
# same split, and the list API's `type` filter, which queries on it.
MESSAGING_ACTION_TYPES: Final[list[str]] = [
    "function_email",
    "function_sms",
    "function_push",
]

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
    "internal-event",
}


def hog_flow_origin_product_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration.
    return list(HogFlow.OriginProduct.choices)


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

    class OriginProduct(models.TextChoices):
        LOOPS = "loops", "Loops"

    name = models.CharField(max_length=400, null=True, blank=True)
    description = models.TextField(blank=True, default="")
    version = models.IntegerField(default=1)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=State, default=State.DRAFT)
    # The product surface that owns this workflow, so that surface can list only its own flows.
    # Null for workflows built directly in the workflows UI or over the API.
    origin_product = models.CharField(
        max_length=40, choices=hog_flow_origin_product_choices, null=True, blank=True, db_index=False
    )

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

    # Automatic per-workflow email pause, set by the deliverability detector when this workflow's
    # complaint or hard-bounce rate crosses a threshold. All workflow email shares one SES account,
    # so one bad workflow degrades every customer's deliverability. Enforced at the send choke point
    # in the email worker. Only the resume endpoint (or a staff admin action) clears it; a normal
    # workflow update must not, so the API exposes these read-only.
    email_sending_paused_at = models.DateTimeField(null=True, blank=True)
    email_sending_paused_reason = models.TextField(blank=True, default="", db_default="")
    # Start bound for every detector window on this workflow. Without it, resuming instantly
    # re-trips on the feedback that caused the pause in the first place.
    email_sending_resumed_at = models.DateTimeField(null=True, blank=True)
    # Who paused it: "auto" for the deliverability detector, "staff" for a PostHog admin. A staff
    # pause is not customer-resumable, so the resume endpoint refuses it. Empty when not paused.
    email_sending_paused_by = models.CharField(max_length=16, blank=True, default="", db_default="")
    # When the deliverability detector last warned this workflow's admins that its rates are
    # approaching the pause thresholds. Bounds how often the warning email can repeat.
    email_sending_warned_at = models.DateTimeField(null=True, blank=True)

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
