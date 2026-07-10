from django.core.exceptions import ValidationError
from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDModel


def default_period() -> dict:
    # Default lookback: the brief covers the last 7 days, compared against the 7 days before.
    return {"type": "last_n_days", "days": 7}


class ResourceType(models.TextChoices):
    INSIGHT = "insight"
    DASHBOARD = "dashboard"
    ANNOTATION = "annotation"
    EXPERIMENT = "experiment"
    # Events have no Django model, so an event link carries only the cached columns (no FK).
    EVENT = "event"


class ActionType(models.TextChoices):
    ADVISORY = "advisory"
    CREATE_PR = "create_pr"
    INSTRUMENT_EVENT = "instrument_event"
    CREATE_INSIGHT = "create_insight"


class ActionStatus(models.TextChoices):
    PROPOSED = "proposed"
    EXECUTING = "executing"
    DONE = "done"
    FAILED = "failed"


def default_action() -> dict:
    # Forward-compatible envelope for a future action executor. The model emits only a summary
    # today; persist wraps it via build_action, so every opportunity starts as a proposed advisory.
    return {"type": ActionType.ADVISORY.value, "summary": "", "params": {}, "status": ActionStatus.PROPOSED.value}


def build_action(summary: str) -> dict:
    """Wrap the LLM's free-text next step in the structured advisory envelope."""
    return {
        "type": ActionType.ADVISORY.value,
        "summary": summary,
        "params": {},
        "status": ActionStatus.PROPOSED.value,
    }


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
    # Per-config tunables overriding config.py defaults; shape/ranges: config.BriefSettings.
    settings = models.JSONField(default=dict)
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

    # Configs soft-delete in normal operation; a hard delete (e.g. via admin) is deliberate and
    # cascades to the briefs generated for that config rather than orphaning them.
    config = models.ForeignKey(BriefConfig, on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING)
    trigger = models.CharField(max_length=20, choices=Trigger.choices)
    # Period spec resolved to explicit dates in-activity; shape: {"type": "last_n_days", "days": 7}
    # or {"type": "since_last_run"}. See temporal/activities.resolve_period.
    period = models.JSONField(default=default_period)
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

    # persist always sets this; a hard-deleted brief cascades to the opportunities it first surfaced.
    first_seen_brief = models.ForeignKey(ProductBrief, on_delete=models.CASCADE)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    title = models.CharField(max_length=400)
    summary = models.TextField()
    # Structured action envelope; shape: default_action(). Advisory-only today; forward-compatible
    # for a future executor. The LLM still emits a free-text summary (OpportunityOut.suggested_action)
    # that persist wraps via build_action.
    action = models.JSONField(default=default_action)
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


class ResourceLink(PulseModel):
    """Evidence link from an opportunity to a PostHog resource it cites.

    One opportunity has many links. Per-type nullable FKs (not a GenericForeignKey, which is
    rejected repo-wide) point at the cited resource; the cached `resource_type`/`ref`/`label`/`url`
    columns keep the link meaningful for events (no Django model) and after a FK nulls.
    """

    # A hard-deleted brief cascades to its opportunities, which cascade to their links.
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="resource_links")

    # Deliberately SET_NULL, not CASCADE or an exactly-one constraint like DashboardTile: an
    # opportunity's evidence history must survive the cited resource being deleted. These target
    # non-hot tables, so real DB constraints are fine (no db_constraint=False).
    insight = models.ForeignKey(
        "product_analytics.Insight", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    dashboard = models.ForeignKey(
        "dashboards.Dashboard", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    annotation = models.ForeignKey(
        "annotations.Annotation", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    experiment = models.ForeignKey(
        "experiments.Experiment", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    resource_type = models.CharField(max_length=20, choices=ResourceType.choices)
    # short_id (insight), id (dashboard/annotation/experiment), or event name.
    ref = models.CharField(max_length=400)
    label = models.CharField(max_length=400)
    # Deep link into the app; "" when the ref has no navigable target.
    url = models.CharField(max_length=1000, blank=True, default="")

    # Maps each DB-modeled resource_type to the FK field that must be set for it.
    _FK_FIELD_BY_TYPE = {
        ResourceType.INSIGHT: "insight",
        ResourceType.DASHBOARD: "dashboard",
        ResourceType.ANNOTATION: "annotation",
        ResourceType.EXPERIMENT: "experiment",
    }

    def clean(self) -> None:
        # No hard CheckConstraint: SET_NULL nulls the FK when a resource is deleted, which would
        # violate an "FK-matching-resource_type is set" constraint even though the link is still
        # valid history. So this is enforced at write time (creation), not by the DB forever.
        super().clean()
        fk_field = self._FK_FIELD_BY_TYPE.get(ResourceType(self.resource_type)) if self.resource_type else None
        if fk_field is not None and getattr(self, f"{fk_field}_id") is None:
            raise ValidationError(f"resource_type '{self.resource_type}' requires the '{fk_field}' FK to be set.")
