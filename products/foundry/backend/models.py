"""
Django models for foundry.

Keep models thin — business logic belongs in logic/.
Use types from facade/enums.py where applicable.
Avoid ForeignKeys to models outside this app; if needed,
disallow reverse relations with related_name='+'.
"""

import uuid

from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin

from .facade.enums import BetEventKind, BetState, BetVerdict, ExecutionMode, NodeStatus


class Bet(TeamScopedRootMixin):
    """A hypothesis with a budget, one success metric, and guardrails.

    Funded bets get a feature flag and a draft experiment; external
    orchestrators report progress via BetEvents; the market renders the
    verdict through the experiment.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    slug = models.SlugField(max_length=200)
    hypothesis = models.TextField()
    success_metric = models.JSONField(default=dict)
    guardrails = models.JSONField(default=list, blank=True)
    budget = models.JSONField(default=dict, blank=True)
    exposure_plan = models.JSONField(default=dict, blank=True)
    sources = models.JSONField(default=list, blank=True)
    ttl = models.DateTimeField(null=True, blank=True)
    state = models.CharField(
        max_length=32,
        choices=[(s.value, s.value) for s in BetState],
        default=BetState.DRAFTED,
    )
    verdict = models.CharField(
        max_length=32,
        choices=[(v.value, v.value) for v in BetVerdict],
        null=True,
        blank=True,
    )
    iteration = models.PositiveIntegerField(default=1)
    execution_mode = models.CharField(
        max_length=16,
        choices=[(m.value, m.value) for m in ExecutionMode],
        default=ExecutionMode.EXTERNAL,
    )
    run_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Managed-mode execution config: {image/template, command, env allowlist, caps}.",
    )
    memory_repo_url = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        help_text="Git-backed memory repo (e.g. Gitea) cloned into managed nodes' sandboxes at a conventional path.",
    )
    gate_config = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "The gauntlet's constraint battery: {checks: [{name, check_type, required, params}], "
            "protected_paths: [...], artifact: {template}}. Owned outside the builder's reach."
        ),
    )
    feature_flag = models.ForeignKey(
        "feature_flags.FeatureFlag",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    experiment = models.ForeignKey(
        "experiments.Experiment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "posthog.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "slug"], name="unique_bet_slug_per_team"),
        ]

    def __str__(self) -> str:
        return self.slug


class BetEvent(TeamScopedRootMixin):
    """Append-only event log for a bet.

    The only write surface for external orchestrators. Events are immutable:
    the API exposes create and list, never update or delete.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    bet = models.ForeignKey(Bet, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32, choices=[(k.value, k.value) for k in BetEventKind])
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        "posthog.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["bet", "created_at"], name="foundry_betevent_bet_ts"),
        ]

    def __str__(self) -> str:
        return f"{self.bet_id}:{self.kind}"


class BetNode(TeamScopedRootMixin):
    """A queryable registry of a managed or external run's node tree.

    Projected from BetEvents (node.spawned / node.finished / node.failed / budget.exceeded) —
    events remain the source of truth; this table exists so the tree can be queried and
    rendered without replaying the whole event log.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    bet = models.ForeignKey(Bet, on_delete=models.CASCADE, related_name="nodes")
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    node_id = models.CharField(max_length=200, help_text="Orchestrator-supplied identifier, unique per bet.")
    status = models.CharField(
        max_length=16,
        choices=[(s.value, s.value) for s in NodeStatus],
        default=NodeStatus.SPAWNED,
    )
    runner = models.CharField(max_length=200, blank=True, help_text="Free-form label, e.g. 'claude-code'.")
    depth = models.PositiveIntegerField(default=0)
    max_cost = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    max_depth = models.PositiveIntegerField(null=True, blank=True)
    max_children = models.PositiveIntegerField(null=True, blank=True)
    cost_so_far = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    sandbox_external_id = models.CharField(max_length=200, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["bet", "node_id"], name="unique_betnode_node_id_per_bet"),
        ]
        indexes = [
            models.Index(fields=["bet", "depth"], name="foundry_betnode_bet_depth"),
        ]

    def __str__(self) -> str:
        return f"{self.bet_id}:{self.node_id}"
