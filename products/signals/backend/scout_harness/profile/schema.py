"""Typed schema for the project profile inventory payload.

`build_inventory` returns an `Inventory` instance; `compute_project_profile` persists
`inventory.model_dump(mode="json")` into the `SignalProjectProfile.payload` jsonb column.

The model is the single source of truth for the payload shape. Storage stays jsonb — the
payload is written by one builder, read whole, and never field-queried, so relational
columns would buy no query benefit and a migration per section as coverage grows. But the
jsonb is *schema-backed*, not schemaless: the scout skills read the inventory by key, so
validating the shape on write keeps them from silently drifting when sections are added or
reshaped (`extra="forbid"` makes a builder emitting an unmodeled key fail loudly in tests
rather than dropping data a skill might depend on).

Nullability mirrors the underlying Django fields: every serialized timestamp is optional,
and columns that are `null=True` at the DB layer (`HogFunction.type`/`kind`,
`AlertConfiguration.calculation_interval`, `Cohort.count`) are optional here too. Bump
`INVENTORY_SOURCE_VERSION` in `builders.py` when the shape changes meaningfully so
`get_project_profile` invalidates cached rows built on the old shape.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Section(BaseModel):
    # Forbid unmodeled keys so the builders and this schema can't drift apart unnoticed —
    # an extra key is a contract change the scout skills need to know about, so surface it.
    model_config = ConfigDict(extra="forbid")


class ProjectContext(_Section):
    product_description: str | None
    app_urls: list[str]


class ProductIntentEntry(_Section):
    product_type: str
    activated_at: str | None
    created_at: str | None


class IntegrationEntry(_Section):
    kind: str
    created_at: str | None


class ExternalDataSourceEntry(_Section):
    source_type: str
    status: str
    prefix: str
    created_at: str | None


class SignalSourceConfigEntry(_Section):
    source_product: str
    source_type: str


class SignalSourceConfigs(_Section):
    enabled: list[SignalSourceConfigEntry]
    disabled: list[SignalSourceConfigEntry]


class StatusCount(_Section):
    status: str
    count: int


class ExistingInboxReports(_Section):
    total: int
    by_status: list[StatusCount]


class ScopeActivity(_Section):
    scope: str
    edits: int
    users: int
    last_edit: str | None


class RecentActivity(_Section):
    window_days: int
    by_scope: list[ScopeActivity]


class ReviewerCorrection(_Section):
    report_id: str
    report_title: str | None
    before: list[str]
    after: list[str]
    at: str | None


class RecentReviewerCorrections(_Section):
    window_days: int
    corrections: list[ReviewerCorrection]


class DashboardEntry(_Section):
    id: int
    name: str
    last_accessed_at: str | None
    last_refresh: str | None
    created_at: str | None


class SurveyEntry(_Section):
    id: str
    name: str
    type: str
    status: str
    updated_at: str | None


class RecentSurveys(_Section):
    total_count: int
    active_count: int
    recent: list[SurveyEntry]


class FeatureFlagEntry(_Section):
    id: int
    key: str
    name: str
    active: bool
    updated_at: str | None


class RecentFeatureFlags(_Section):
    total_count: int
    active_count: int
    recent: list[FeatureFlagEntry]


class ExperimentEntry(_Section):
    id: int
    name: str
    status: str
    feature_flag_key: str | None
    updated_at: str | None


class RecentExperiments(_Section):
    total_count: int
    running_count: int
    recent: list[ExperimentEntry]


class AlertEntry(_Section):
    id: str
    name: str
    enabled: bool
    state: str
    calculation_interval: str | None
    insight_id: int | None
    created_at: str | None


class RecentAlerts(_Section):
    total_count: int
    enabled_count: int
    recent: list[AlertEntry]


class HogFunctionEntry(_Section):
    id: str
    name: str
    type: str | None
    kind: str | None
    enabled: bool
    updated_at: str | None


class RecentHogFunctions(_Section):
    total_count: int
    enabled_count: int
    recent: list[HogFunctionEntry]


class HogFlowEntry(_Section):
    id: str
    name: str
    status: str
    updated_at: str | None


class RecentHogFlows(_Section):
    total_count: int
    active_count: int
    recent: list[HogFlowEntry]


class NotebookEntry(_Section):
    short_id: str
    title: str
    last_modified_at: str | None


class RecentNotebooks(_Section):
    total_count: int
    recent: list[NotebookEntry]


class CohortEntry(_Section):
    id: int
    name: str
    is_static: bool
    count: int | None
    created_at: str | None


class RecentCohorts(_Section):
    total_count: int
    recent: list[CohortEntry]


class ActionEntry(_Section):
    id: int
    name: str
    updated_at: str | None


class RecentActions(_Section):
    total_count: int
    recent: list[ActionEntry]


class KnowledgeSourceEntry(_Section):
    id: str
    name: str
    source_type: str
    status: str
    updated_at: str | None


class BusinessKnowledge(_Section):
    total_count: int
    ready_count: int
    document_count: int
    chunk_count: int
    recent: list[KnowledgeSourceEntry]


class TopEvent(_Section):
    event: str
    count: int
    distinct_users: int
    recent_24h_count: int
    recent_24h_users: int
    first_seen: str | None
    last_seen: str | None


class Inventory(_Section):
    """The deterministic inventory layer of a `SignalProjectProfile.payload`.

    Field order matches `build_inventory`'s assembly order so the serialized jsonb keeps a
    stable key order across builds. `top_events` is `None` (not `[]`) when the ClickHouse
    query fails, so the scout can tell "no captures" apart from "couldn't compute".
    """

    project_context: ProjectContext
    products_in_use: list[str]
    product_intents: list[ProductIntentEntry]
    integrations: list[IntegrationEntry]
    external_data_sources: list[ExternalDataSourceEntry]
    signal_source_configs: SignalSourceConfigs
    existing_inbox_reports: ExistingInboxReports
    recent_activity: RecentActivity
    recent_reviewer_corrections: RecentReviewerCorrections
    recent_dashboards: list[DashboardEntry]
    recent_surveys: RecentSurveys
    recent_feature_flags: RecentFeatureFlags
    recent_experiments: RecentExperiments
    recent_alerts: RecentAlerts
    recent_hog_functions: RecentHogFunctions
    recent_hog_flows: RecentHogFlows
    recent_notebooks: RecentNotebooks
    recent_cohorts: RecentCohorts
    recent_actions: RecentActions
    business_knowledge: BusinessKnowledge
    top_events: list[TopEvent] | None
