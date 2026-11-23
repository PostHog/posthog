"""Django models for stacks.

The stacks app lives on its own database, so references to users and to entities in other products are
plain ids with no foreign key.
"""

from __future__ import annotations

from django.db import models

from posthog.models.scoping.product_mixin import ProductTeamModel
from posthog.models.utils import uuid7

from .facade.enums import BindingOrigin, BindingStatus, DiffStatus, PushStatus

DEFAULT_MAX_REMOVALS = 5


class Stack(ProductTeamModel):
    """One folder of definitions pushed to one project. Its identity is (team, name)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # The exact project the stack belongs to. `team_id` is its canonical parent, which `ProductTeamModel` writes, so
    # every lookup and uniqueness rule keys on this instead: two environments never share a stack.
    target_team_id = models.BigIntegerField()
    name = models.CharField(max_length=100)
    repository = models.CharField(max_length=500, blank=True, default="")
    created_by_id = models.BigIntegerField(null=True)
    organization_id = models.CharField(max_length=64)
    # Context pages belong to the organization's one wiki, so a stack manages them only after an organization admin
    # turns this on.
    context_pages_enabled = models.BooleanField(default=False)
    # Moves with every saved record. A diff is pushable only while it still equals the serial it was computed
    # against.
    serial = models.IntegerField(default=0)
    # Moves with every change to the bindings (adopt, detach) or to the context page setting. A diff is pushable only
    # while it is unchanged.
    revision = models.IntegerField(default=0)
    # Moves with every secret set or removed. A diff is pushable only while it is unchanged.
    secret_revision = models.IntegerField(default=0)
    max_removals = models.PositiveIntegerField(default=DEFAULT_MAX_REMOVALS)
    # The push lease. Admission takes it for one attempt, the running worker extends it, and a takeover after
    # expiry increases the generation so the old worker's next saved record is refused.
    lease_attempt_id = models.UUIDField(null=True, blank=True)
    lease_generation = models.IntegerField(default=0)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    # A push ended without a known outcome. Pushes wait until a person reconciles with a diff computed since.
    needs_reconcile = models.BooleanField(default=False)
    uncertain_since = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["target_team_id", "name"], name="stacks_unique_name_per_project")
        ]
        indexes = [
            models.Index(
                fields=["lease_expires_at"],
                name="stacks_stack_lease_idx",
                condition=models.Q(lease_attempt_id__isnull=False),
            )
        ]

    def __str__(self) -> str:
        return self.name


class StackRecordVersion(ProductTeamModel):
    """The engine's record of what one stack made, as of one push. Every push that changes it writes a new version.

    Encrypted at rest and never returned by an API, because it can hold secret values.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name="record_versions")
    serial = models.IntegerField()
    encrypted_record = models.BinaryField()
    pushed_by_diff_id = models.UUIDField(null=True, blank=True)
    # The push attempt that wrote this version. One attempt keeps one row and replaces its bytes as it goes.
    push_attempt_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["stack", "serial"], name="stacks_unique_record_serial"),
        ]
        indexes = [
            models.Index(
                fields=["push_attempt_id"],
                name="stacks_record_attempt_idx",
                condition=models.Q(push_attempt_id__isnull=False),
            )
        ]


class StackDiff(ProductTeamModel):
    """A saved diff: what a push of one description would change, and that push's own progress.

    The description, the saved diff and every field value can hold secrets, so the first two are encrypted and
    `diff` holds only redacted values.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name="diffs")
    # The exact project the route resolved and the credential was authorized for. Every run of this diff targets
    # it unchanged, even when `team_id` is its parent.
    target_team_id = models.BigIntegerField()
    encrypted_description = models.BinaryField()
    description_hash = models.CharField(max_length=64)
    # Kinds in the description, kept in the clear so scope checks need no decryption.
    kinds = models.JSONField(default=list)
    source_repository = models.CharField(max_length=500, blank=True, default="")
    source_branch = models.CharField(max_length=500, blank=True, default="")
    source_commit = models.CharField(max_length=100, blank=True, default="")
    status = models.CharField(max_length=16, choices=DiffStatus.choices, default=DiffStatus.RUNNING.value)
    diff = models.JSONField(null=True, blank=True)
    encrypted_saved_diff = models.BinaryField(null=True, blank=True)
    base_serial = models.IntegerField(null=True, blank=True)
    base_revision = models.IntegerField(null=True, blank=True)
    base_secret_revision = models.IntegerField(null=True, blank=True)
    # The changes the engine planned, as (action, kind, key, entity_id), unredacted and never returned. Admission
    # reserves identities from this, not from the public `diff`.
    planned = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    # A diff still running after this is closed as failed.
    deadline_at = models.DateTimeField()
    created_by_id = models.BigIntegerField(null=True)
    # The credential that asked, as {"type", "id"}, and never its secret. The worker checks it still exists.
    created_by_grant = models.JSONField(default=dict)
    # The scopes checked when the diff was admitted. The worker mints exactly these.
    run_scopes = models.JSONField(default=list)
    push_attempt_id = models.UUIDField(null=True, blank=True)
    push_generation = models.IntegerField(null=True, blank=True)
    pushed_by_id = models.BigIntegerField(null=True, blank=True)
    pushed_by_grant = models.JSONField(default=dict, blank=True)
    push_scopes = models.JSONField(default=list, blank=True)
    # The id of the worker's access token row, so a takeover can revoke it. Never the token itself.
    push_token_id = models.UUIDField(null=True, blank=True)
    push_status = models.CharField(max_length=16, choices=PushStatus.choices, null=True, blank=True)
    push_errors = models.JSONField(default=list, blank=True)
    push_started_at = models.DateTimeField(null=True, blank=True)
    push_finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        indexes = [
            models.Index(fields=["stack", "status"], name="stacks_diff_stack_status_idx"),
            models.Index(
                fields=["expires_at"],
                name="stacks_diff_saved_expiry_idx",
                condition=models.Q(encrypted_saved_diff__isnull=False),
            ),
            models.Index(
                fields=["deadline_at"],
                name="stacks_diff_running_idx",
                condition=models.Q(status="running"),
            ),
            models.Index(
                fields=["push_attempt_id"],
                name="stacks_diff_attempt_idx",
                condition=models.Q(push_attempt_id__isnull=False),
            ),
            models.Index(
                fields=["push_token_id"],
                name="stacks_diff_token_idx",
                condition=models.Q(push_token_id__isnull=False),
            ),
        ]


class StackBinding(ProductTeamModel):
    """The bindings index: which entity a stack's definition made or adopted."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name="bindings")
    kind = models.CharField(max_length=64)
    # Long enough for the longest natural key a kind allows, such as a wiki path.
    key = models.CharField(max_length=512)
    entity_id = models.CharField(max_length=512)
    # Where an entity can be claimed only once: "team:<id>", or "organization:<id>" for a kind that belongs to the
    # whole organization, such as a context page.
    claim_scope = models.CharField(max_length=80)
    # The body paths code owns for this binding, from the last pushed definition. The write lock reads them.
    owned_fields = models.JSONField(default=list)
    status = models.CharField(max_length=16, choices=BindingStatus.choices, default=BindingStatus.BOUND.value)
    origin = models.CharField(max_length=16, choices=BindingOrigin.choices, default=BindingOrigin.CREATED.value)
    source_file = models.CharField(max_length=1000, blank=True, default="")
    source_export = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["stack", "kind", "key"], name="stacks_unique_binding_key"),
            # One entity is managed by at most one stack in its claim scope. A detached binding manages nothing.
            models.UniqueConstraint(
                fields=["claim_scope", "kind", "entity_id"],
                condition=models.Q(status__in=["pending", "bound"]),
                name="stacks_unique_managed_entity",
            ),
        ]


class StackNaturalClaim(ProductTeamModel):
    """A natural identity, such as a flag key, an event name or a wiki path, that one stack plans to create or adopt.

    Admission takes it before a push reaches the API, so two stacks that both plan to create one key cannot both
    send it. It is released when the stack no longer manages that identity.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name="natural_claims")
    claim_scope = models.CharField(max_length=80)
    kind = models.CharField(max_length=64)
    key = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["claim_scope", "kind", "key"], name="stacks_unique_natural_claim"),
        ]


class StackSecret(ProductTeamModel):
    """A secret value a stack's definitions name with `secret('NAME')`. Encrypted at rest and never returned."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    stack = models.ForeignKey(Stack, on_delete=models.CASCADE, related_name="secrets")
    name = models.CharField(max_length=100)
    encrypted_value = models.BinaryField()
    updated_by_id = models.BigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(ProductTeamModel.Meta):
        constraints = [models.UniqueConstraint(fields=["stack", "name"], name="stacks_unique_secret_name")]
