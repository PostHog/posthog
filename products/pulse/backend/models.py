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
    # Free text steering the LLM; capped because it is interpolated into the synthesis prompt.
    focus_prompt = models.TextField(blank=True, default="", max_length=2000)
    # Shape: BriefAnchorsSerializer (api/brief.py) — {"dashboards": [int], "insights": [short_id str]}
    anchors = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)
    # Soft delete: configs are recoverable and brief history keeps pointing at them.
    deleted = models.BooleanField(default=False)


class ProductBrief(PulseModel):
    class Status(models.TextChoices):
        GENERATING = "generating"
        READY = "ready"
        QUIET = "quiet"
        FAILED = "failed"

    class Trigger(models.TextChoices):
        ON_DEMAND = "on_demand"
        SCHEDULED = "scheduled"

    # Configs soft-delete in normal operation; SET_NULL is the backstop for hard deletes
    # (e.g. via admin) so brief history survives those too.
    config = models.ForeignKey(BriefConfig, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING)
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    # Lookback window: the brief covers the last N days, compared against the N days before.
    period_days = models.IntegerField(default=7)
    # Shape: list[SectionOut] — see generation/schemas.py (the LLM structured-output schema).
    sections = models.JSONField(default=list)
    sources_used = models.JSONField(default=list)
    error = models.TextField(null=True, blank=True)
    feedback = models.JSONField(default=dict)

    class Meta(PulseModel.Meta):
        # The stale-brief reaper sweeps GENERATING rows cross-team every few minutes on an
        # append-only table; a partial index keeps that O(stranded rows), not O(all briefs ever).
        indexes = [
            models.Index(
                fields=["updated_at"],
                name="pulse_brief_generating_idx",
                condition=models.Q(status="generating"),
            )
        ]


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
    # Shape: list[EvidenceRef] — see sources/base.py.
    evidence = models.JSONField(default=list)
    # {"insight_short_id": str, "series_index": int} | null
    metric_ref = models.JSONField(null=True, blank=True)
    # snapshot of metric value(s) at creation, for the future impact loop
    baseline = models.JSONField(null=True, blank=True)
    fingerprint = models.CharField(max_length=512)
    feedback = models.JSONField(default=dict)

    class Meta(PulseModel.Meta):
        # Dedup race guard: concurrent persists can't double-insert a fingerprint (persist
        # bulk_creates with ignore_conflicts). The unique index doubles as the lookup index.
        constraints = [models.UniqueConstraint(fields=["team", "fingerprint"], name="pulse_opp_team_fp_unique")]
