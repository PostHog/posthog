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

from .facade.enums import BetEventKind, BetState, BetVerdict


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
