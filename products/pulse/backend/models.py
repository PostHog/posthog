from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class PulseModel(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    """Abstract base for pulse models: fail-closed team scoping + lock-free hot-table FKs."""

    # `objects` (TeamScopedManager) inherited from TeamScopedRootMixin stays fail-closed for
    # explicit user code. `all_teams` is the unscoped sibling for Django framework internals
    # (admin querysets, related-object access, prefetch_related) that must not filter by team;
    # `default_manager_name` routes `_default_manager` / `_base_manager` there.
    all_teams = models.Manager()  # noqa: DJ012

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating the
    # tables takes no lock on those parents. created_by overrides CreatedMetaFields for the same reason.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )

    class Meta:
        abstract = True
        default_manager_name = "all_teams"


class BriefConfig(PulseModel):
    name = models.CharField(max_length=400)
    focus_prompt = models.TextField(blank=True, default="")
    # {"dashboards": [int], "insights": [short_id str]}
    anchors = models.JSONField(default=dict)
    # What the focus is driving toward, e.g. "increase subscription usage". User-authored
    # free text — sanitized at the prompt-render boundary, never trusted raw in prompts.
    goal = models.TextField(blank=True, default="")
    # {"insight_short_id": str} | null — a subset of Opportunity.metric_ref (no series_index:
    # the goal metric is always the insight's first series)
    goal_metric = models.JSONField(null=True, blank=True)
    enabled = models.BooleanField(default=True)


class ProductBrief(PulseModel):
    class Status(models.TextChoices):
        GENERATING = "generating"
        READY = "ready"
        QUIET = "quiet"
        FAILED = "failed"

    class Trigger(models.TextChoices):
        ON_DEMAND = "on_demand"
        SCHEDULED = "scheduled"

    # SET_NULL: deleting a config must not destroy the brief history generated from it.
    config = models.ForeignKey(BriefConfig, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING)
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    period_days = models.IntegerField(default=7)
    # list[{"kind": str, "title": str, "markdown": str, "citations": list, "confidence": float}]
    sections = models.JSONField(default=list)
    # Goal-investigation findings, in citation order (`query:<n>` refs are 1-based indexes into
    # this list): list[{"question": str, "hogql": str, "result_summary": str, "succeeded": bool,
    # "citations": list[str]}]. `citations` carries code-generated refs (e.g. `session:<id>` for
    # replay-pattern findings); HogQL findings leave it empty. Empty list for goal-less briefs.
    investigation = models.JSONField(default=list)
    sources_used = models.JSONField(default=list)
    error = models.TextField(null=True, blank=True)
    feedback = models.JSONField(default=dict)

    @property
    def has_goal(self) -> bool:
        """Whether the brief was generated for a config with a non-blank goal."""
        return self.config is not None and bool(self.config.goal.strip())


class Opportunity(PulseModel):
    class Kind(models.TextChoices):
        BUILD = "build"
        FIX = "fix"
        INSTRUMENT = "instrument"

    class Status(models.TextChoices):
        OPEN = "open"
        DISMISSED = "dismissed"
        ACTED = "acted"
        RESOLVED = "resolved"

    first_seen_brief = models.ForeignKey(ProductBrief, on_delete=models.SET_NULL, null=True, blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=400)
    summary = models.TextField()
    suggested_action = models.TextField(blank=True, default="")
    # list[{"type": "insight"|"dashboard"|"annotation", "ref": str, "label": str}]
    evidence = models.JSONField(default=list)
    # {"insight_short_id": str, "series_index": int} | null
    metric_ref = models.JSONField(null=True, blank=True)
    # snapshot of metric value(s) at creation, for the future impact loop
    baseline = models.JSONField(null=True, blank=True)
    # Set by goal-conditioned synthesis: this opportunity plausibly advances the focus goal.
    goal_relevant = models.BooleanField(default=False)
    # {"hypothesis": str, "flag_key_suggestion": str, "target_metric": {"insight_short_id": str},
    # "variant_sketch": str} | null — only ever set on goal-relevant opportunities (persist nulls
    # it otherwise).
    proposed_experiment = models.JSONField(null=True, blank=True)
    fingerprint = models.CharField(max_length=512)
    feedback = models.JSONField(default=dict)

    class Meta(PulseModel.Meta):
        # Dedup race guard: concurrent persists can't double-insert a fingerprint (persist
        # bulk_creates with ignore_conflicts). The unique index doubles as the lookup index.
        constraints = [models.UniqueConstraint(fields=["team", "fingerprint"], name="pulse_opp_team_fp_unique")]
