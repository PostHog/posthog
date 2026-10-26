from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class AgentOperation(TeamScopedRootMixin, UUIDModel):
    """One goal that an external MCP client delegates to PostHog AI.

    The operation outlives the runs that work on it: a reply after a terminal run resumes into a
    new run, and the operation id stays the same. The project and the delegated permissions are
    fixed when the operation starts.
    """

    class State(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        NEEDS_INPUT = "needs_input", "Needs input"
        CANCELLING = "cancelling", "Cancelling"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    TERMINAL_STATES = frozenset({State.SUCCEEDED, State.FAILED, State.CANCELLED, State.EXPIRED})
    ACTIVE_STATES = frozenset({State.QUEUED, State.RUNNING, State.NEEDS_INPUT, State.CANCELLING})

    class Approvals(models.TextChoices):
        CLIENT = "client", "Client"
        NONE = "none", "None"

    class ParentCredentialKind(models.TextChoices):
        PERSONAL_API_KEY = "personal_api_key", "Personal API key"
        OAUTH_TOKEN_FAMILY = "oauth_token_family", "OAuth refresh-token family"
        OAUTH_APPLICATION = "oauth_application", "OAuth application"
        NONE = "none", "None"

    # db_constraint=False on the team/user FKs: an FK constraint locks those hot tables and stalls
    # deploys. Django still enforces the relation and on_delete at the app level.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    conversation = models.ForeignKey(
        "posthog_ai.Conversation", on_delete=models.CASCADE, related_name="agent_operations", db_index=False
    )
    task_id = models.UUIDField(null=True, blank=True)
    run_id = models.UUIDField(null=True, blank=True)

    client_request_id = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    goal = models.TextField()

    state = models.CharField(max_length=16, choices=State.choices, default=State.QUEUED)
    # "client": the run asks for approvals and the client's UI answers them. "none": the run asks for none.
    approvals = models.CharField(max_length=8, choices=Approvals.choices, default=Approvals.NONE)
    state_reason = models.CharField(max_length=64, null=True, blank=True)

    granted_scopes = models.JSONField(default=list)
    parent_credential_kind = models.CharField(max_length=32, choices=ParentCredentialKind.choices)
    parent_credential_ref = models.CharField(max_length=128, null=True, blank=True)

    repository = models.CharField(max_length=255, null=True, blank=True)
    requested_ref = models.CharField(max_length=255, null=True, blank=True)
    resolved_commit = models.CharField(max_length=40, null=True, blank=True)

    result = models.JSONField(null=True, blank=True)
    # The output of the run that the operation last handled, so an old result is not read again
    # after a reply resumes the work.
    handled_output_run_id = models.UUIDField(null=True, blank=True)
    pending_permission_request = models.JSONField(null=True, blank=True)
    # The run log shows an answered approval as open until the sandbox records the answer, so a read
    # in between must not bring it back.
    answered_permission_request_id = models.CharField(max_length=200, null=True, blank=True)
    progress_snapshot = models.JSONField(default=dict, blank=True)

    deadline_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_ai_agent_operation"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "client_request_id"], name="agent_operation_client_request_uniq"
            ),
        ]
        indexes = [
            models.Index(fields=["user", "state"], name="agent_operation_user_state_idx"),
            models.Index(fields=["parent_credential_kind", "parent_credential_ref"], name="agent_operation_parent_idx"),
            models.Index(fields=["conversation", "created_at"], name="agent_operation_conv_idx"),
        ]

    @property
    def is_terminal(self) -> bool:
        return self.state in self.TERMINAL_STATES


class AgentOperationReply(TeamScopedRootMixin, UUIDModel):
    """One reply that a client sent to an operation, kept so that a retried reply is delivered once."""

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    operation = models.ForeignKey(AgentOperation, on_delete=models.CASCADE, related_name="replies", db_index=False)
    client_request_id = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_ai_agent_operation_reply"
        constraints = [
            models.UniqueConstraint(
                fields=["operation", "client_request_id"], name="agent_operation_reply_request_uniq"
            ),
        ]
