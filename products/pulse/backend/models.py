from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


class BriefConfig(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    # `objects` (TeamScopedManager) inherited from TeamScopedRootMixin stays fail-closed for
    # explicit user code. `all_teams` is the unscoped sibling for Django framework internals
    # (admin querysets, related-object access, prefetch_related) that must not filter by team;
    # `default_manager_name` routes `_default_manager` / `_base_manager` there.
    all_teams = models.Manager()  # noqa: DJ012

    # FKs to the hot posthog_team / posthog_user tables use db_constraint=False so creating this
    # table takes no lock on those parents. created_by overrides CreatedMetaFields for the same reason.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    name = models.CharField(max_length=400)
    focus_prompt = models.TextField(blank=True, default="")
    # {"dashboards": [int], "insights": [short_id str]}
    anchors = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)

    class Meta:
        default_manager_name = "all_teams"


class ProductBrief(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class Status(models.TextChoices):
        GENERATING = "generating"
        READY = "ready"
        QUIET = "quiet"
        FAILED = "failed"

    class Trigger(models.TextChoices):
        ON_DEMAND = "on_demand"
        SCHEDULED = "scheduled"

    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
    config = models.ForeignKey(BriefConfig, on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING)
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    period_days = models.IntegerField(default=7)
    # list[{"kind": str, "title": str, "markdown": str, "citations": list, "confidence": float}]
    sections = models.JSONField(default=list)
    sources_used = models.JSONField(default=list)
    error = models.TextField(null=True, blank=True)
    tokens_used = models.IntegerField(null=True, blank=True)
    feedback = models.JSONField(default=dict)

    class Meta:
        default_manager_name = "all_teams"


class Opportunity(TeamScopedRootMixin, CreatedMetaFields, UpdatedMetaFields, UUIDModel):
    class Kind(models.TextChoices):
        BUILD = "build"
        FIX = "fix"
        INSTRUMENT = "instrument"

    class Status(models.TextChoices):
        OPEN = "open"
        DISMISSED = "dismissed"
        ACTED = "acted"
        RESOLVED = "resolved"

    all_teams = models.Manager()  # noqa: DJ012

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_constraint=False
    )
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
    fingerprint = models.CharField(max_length=512)
    feedback = models.JSONField(default=dict)

    class Meta:
        default_manager_name = "all_teams"
        indexes = [models.Index(fields=["team", "fingerprint"], name="pulse_opp_team_fp_idx")]
