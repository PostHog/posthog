from dataclasses import asdict
from typing import cast

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import DateRange, SourceMap

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.team.team import DEFAULT_CURRENCY
from posthog.models.user import User

from products.marketing_analytics.backend.hogql_queries.adapters.base import ExternalConfig, QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.adapters.self_managed import SelfManagedAdapter
from products.marketing_analytics.backend.hogql_queries.utils import map_url_to_provider
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    explain_conversion_goal,
    list_conversion_goals,
)
from products.marketing_analytics.backend.services.data_source_health import get_data_source_health
from products.marketing_analytics.backend.services.event_suggestions import suggest_conversion_goals
from products.marketing_analytics.backend.services.mapping_suggester import suggest_utm_mappings
from products.marketing_analytics.backend.services.marketing_diagnostic import get_marketing_diagnostic
from products.marketing_analytics.backend.services.utm_audit import run_utm_audit
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

logger = structlog.get_logger(__name__)


@extend_schema_field(
    {
        "type": "array",
        "prefixItems": [{"type": "string"}, {"type": "integer"}],
        "minItems": 2,
        "maxItems": 2,
    }
)
class LabelCountField(serializers.ListField):
    """A `[label, count]` pair — a 2-element tuple of (string, integer)."""


class TestMappingSerializer(serializers.Serializer):
    table_id = serializers.UUIDField()
    source_map = serializers.DictField(child=serializers.CharField(allow_null=True, allow_blank=True))


class UtmAuditQuerySerializer(serializers.Serializer):
    date_from = serializers.CharField(required=False, default="-30d", help_text="Start date for the audit period")
    date_to = serializers.CharField(
        required=False, default=None, allow_null=True, help_text="End date for the audit period"
    )


class UtmIssueSerializer(serializers.Serializer):
    field = serializers.CharField(help_text="The UTM field with the issue (e.g. utm_campaign, utm_source)")
    severity = serializers.ChoiceField(choices=["error", "warning"], help_text="Issue severity level")
    message = serializers.CharField(help_text="Human-readable description of the issue")


class CampaignAuditResultSerializer(serializers.Serializer):
    campaign_name = serializers.CharField(help_text="Campaign name from the ad platform")
    campaign_id = serializers.CharField(help_text="Campaign ID from the ad platform")
    source_name = serializers.CharField(help_text="Integration source name (e.g. google, meta)")
    spend = serializers.FloatField(help_text="Total spend for this campaign in the period")
    clicks = serializers.IntegerField(help_text="Total clicks for this campaign")
    impressions = serializers.IntegerField(help_text="Total impressions for this campaign")
    has_utm_events = serializers.BooleanField(help_text="Whether matching UTM pageview events were found")
    event_count = serializers.IntegerField(help_text="Number of matching UTM pageview events")
    issues = UtmIssueSerializer(many=True, help_text="List of detected UTM configuration issues")


class UtmEventSerializer(serializers.Serializer):
    utm_campaign = serializers.CharField(help_text="UTM campaign value from pageview events")
    utm_source = serializers.CharField(help_text="UTM source value from pageview events")
    event_count = serializers.IntegerField(help_text="Number of pageview events with this UTM combination")
    campaign_match = serializers.ChoiceField(
        choices=["none", "auto", "mapped"],
        help_text="How utm_campaign matched: none, auto (direct name/id), or mapped (manual mapping)",
    )
    source_match = serializers.ChoiceField(
        choices=["none", "auto", "mapped"],
        help_text="How utm_source matched: none, auto (default source), or mapped (custom mapping)",
    )
    matched_campaign = serializers.CharField(allow_null=True, help_text="Name of the matched campaign, if any")


class UtmAuditResponseSerializer(serializers.Serializer):
    total_campaigns = serializers.IntegerField(help_text="Total number of campaigns with spend")
    campaigns_with_issues = serializers.IntegerField(help_text="Number of campaigns with UTM issues")
    campaigns_without_issues = serializers.IntegerField(help_text="Number of campaigns without issues")
    total_spend_at_risk = serializers.FloatField(help_text="Total spend on campaigns with UTM issues")
    results = CampaignAuditResultSerializer(many=True, help_text="Audit results per campaign")
    all_utm_events = UtmEventSerializer(many=True, help_text="All UTM events with match status")


class ConversionGoalSummarySerializer(serializers.Serializer):
    id = serializers.CharField(help_text="Unique id of the goal (event name, action id, or DW goal id)")
    name = serializers.CharField(help_text="Display name of the conversion goal")
    # `kind` is a collision-prone enum name in drf-spectacular, so we expose it as a
    # documented string rather than a ChoiceField to avoid a CI --fail-on-warn break.
    kind = serializers.CharField(
        help_text="Goal type — one of: EventsNode (PostHog event), ActionsNode (PostHog action), DataWarehouseNode (external table)"
    )
    target_label = serializers.CharField(
        help_text="Human-readable target the goal matches (event/action name or table)"
    )
    last_30d_count = serializers.IntegerField(help_text="Count of matching conversion events in the last 30 days")
    integrated_count = serializers.IntegerField(
        allow_null=True,
        help_text="Conversions whose utm_source matches a known integration. Null for DataWarehouseNode goals.",
    )
    events_without_utm_source = serializers.IntegerField(
        allow_null=True,
        help_text="Conversions with no utm_source at all (fix by tagging UTMs). Null for DataWarehouseNode goals.",
    )
    events_with_unmatched_utm_source = serializers.IntegerField(
        allow_null=True,
        help_text="Conversions with a utm_source that matches no integration (fix with custom_source_mappings). Null for DataWarehouseNode goals.",
    )
    non_integrated_count = serializers.IntegerField(
        allow_null=True,
        help_text="Total non-integrated conversions (without + unmatched utm_source). Null for DataWarehouseNode goals.",
    )
    integrated_pct = serializers.FloatField(
        allow_null=True, help_text="Percentage of conversions that are integrated. Null for DataWarehouseNode goals."
    )
    is_misconfigured = serializers.BooleanField(
        help_text="Whether the goal could not be evaluated (e.g. deleted action)"
    )
    misconfig_reason = serializers.CharField(allow_null=True, help_text="Explanation when is_misconfigured is true")
    is_approximate = serializers.BooleanField(
        help_text="True when this 30d count may differ from the dashboard's attribution-windowed number"
    )
    approximation_reason = serializers.CharField(allow_null=True, help_text="Explanation when is_approximate is true")


class ConversionGoalsListResponseSerializer(serializers.Serializer):
    goals = ConversionGoalSummarySerializer(many=True, help_text="One summary entry per configured conversion goal")
    attribution_window_days = serializers.IntegerField(help_text="The team's configured attribution window in days")
    attribution_mode = serializers.CharField(
        help_text="The team's attribution model (e.g. last_touch, first_touch, linear)"
    )
    has_misconfigured = serializers.BooleanField(help_text="True if any goal is misconfigured")


# --- list_data_sources ---


class DataSourcesQuerySerializer(serializers.Serializer):
    source_type = serializers.CharField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Optional. Restrict to one integration (e.g. 'GoogleAds').",
    )


class RequiredTableStatusSerializer(serializers.Serializer):
    table_name = serializers.CharField(
        help_text="Name of the required source table (e.g. 'campaign', 'campaign_stats')"
    )
    present = serializers.BooleanField(help_text="Whether the table exists as a schema on the connected source")
    should_sync = serializers.BooleanField(help_text="Whether the table is enabled for sync")
    status = serializers.CharField(
        allow_null=True,
        help_text="ExternalDataSchema status: Completed/Running/Failed/Paused/Cancelled, or null",
    )
    last_synced_at = serializers.DateTimeField(allow_null=True, help_text="When this table last completed a sync")


class DataSourceHealthEntrySerializer(serializers.Serializer):
    source_type = serializers.CharField(help_text="External data source type key (e.g. 'GoogleAds', 'MetaAds')")
    is_native = serializers.BooleanField(help_text="Whether this is a native marketing integration")
    display_name = serializers.CharField(help_text="Human-readable integration name (e.g. 'Google Ads')")
    connected = serializers.BooleanField(help_text="Whether a live source of this type is connected")
    last_sync_at = serializers.DateTimeField(allow_null=True, help_text="When the source last completed a sync")
    last_sync_status = serializers.CharField(help_text="Sync status: ok/error/stale/tables_failed/not_connected/never")
    last_error = serializers.CharField(allow_null=True, help_text="Latest unresolved sync error message, if any")
    rows_last_24h = serializers.IntegerField(help_text="Rows synced in the last 24 hours")
    rows_last_7d = serializers.IntegerField(help_text="Rows synced in the last 7 days")
    sources_map_present = serializers.BooleanField(help_text="Whether a column mapping exists for this source")
    schema_columns_mapped = serializers.ListField(
        child=serializers.CharField(), help_text="Schema columns currently mapped for this source"
    )
    schema_columns_required_missing = serializers.ListField(
        child=serializers.CharField(), help_text="Required schema columns that are not yet mapped"
    )
    required_tables = RequiredTableStatusSerializer(
        many=True, help_text="Per-required-table sync status for this integration"
    )
    settings_url = serializers.CharField(help_text="URL to the Marketing analytics global settings page")
    schemas_url = serializers.CharField(
        allow_null=True, help_text="URL to the per-source Schemas tab, or null if not connected"
    )
    diagnosis = serializers.CharField(help_text="Human-readable diagnosis of this source's health")
    fix_suggestion = serializers.CharField(allow_null=True, help_text="Suggested fix when the source is unhealthy")


class DataSourceHealthResponseSerializer(serializers.Serializer):
    integrations = DataSourceHealthEntrySerializer(many=True, help_text="One health entry per native integration")
    has_any_data = serializers.BooleanField(help_text="True if any integration synced rows in the last 7 days")
    overall_status = serializers.CharField(help_text="Overall: healthy/degraded/broken/no_sources")
    issues_summary = serializers.ListField(
        child=serializers.CharField(), help_text="Short human-readable summary of detected issues"
    )


# --- explain_conversion_goal ---


class ExplainConversionGoalQuerySerializer(serializers.Serializer):
    goal_id = serializers.CharField(
        required=True, help_text="Id of the conversion goal to explain (from list_conversion_goals)."
    )
    date_from = serializers.CharField(
        required=False, default=None, allow_null=True, help_text="ISO start; defaults to 30 days ago"
    )
    date_to = serializers.CharField(required=False, default=None, allow_null=True, help_text="ISO end; defaults to now")


class GoalEventSampleSerializer(serializers.Serializer):
    event_uuid = serializers.CharField(help_text="UUID of the sampled conversion event")
    timestamp = serializers.DateTimeField(help_text="When the event occurred")
    distinct_id = serializers.CharField(help_text="Distinct id associated with the event")
    utm_source = serializers.CharField(allow_null=True, help_text="utm_source value on the event, if any")
    utm_campaign = serializers.CharField(allow_null=True, help_text="utm_campaign value on the event, if any")
    matched_integration = serializers.CharField(allow_null=True, help_text="Integration the utm_source matched, if any")


class GoalExplanationPeriodSerializer(serializers.Serializer):
    date_from = serializers.CharField(allow_null=True, help_text="Start of the analyzed period (ISO)")
    date_to = serializers.CharField(allow_null=True, help_text="End of the analyzed period (ISO)")


class GoalExplanationSerializer(serializers.Serializer):
    goal_id = serializers.CharField(help_text="Id of the explained conversion goal")
    goal_name = serializers.CharField(help_text="Display name of the conversion goal")
    kind = serializers.CharField(help_text="EventsNode/ActionsNode/DataWarehouseNode")
    period = GoalExplanationPeriodSerializer(help_text="The period the breakdown was computed over")
    total_count = serializers.IntegerField(help_text="Total matching conversion events in the period")
    integrated_count = serializers.IntegerField(
        allow_null=True, help_text="Events whose utm_source matched a known integration. Null for DataWarehouseNode."
    )
    events_without_utm_source = serializers.IntegerField(
        allow_null=True, help_text="Events with no utm_source at all. Null for DataWarehouseNode."
    )
    events_with_unmatched_utm_source = serializers.IntegerField(
        allow_null=True, help_text="Events with a utm_source matching no integration. Null for DataWarehouseNode."
    )
    non_integrated_count = serializers.IntegerField(
        allow_null=True, help_text="Total non-integrated events (without + unmatched). Null for DataWarehouseNode."
    )
    by_event = serializers.ListField(child=LabelCountField(), help_text="List of [event_name, count] pairs")
    by_utm_source = serializers.ListField(child=LabelCountField(), help_text="List of [utm_source, count] pairs")
    by_matched_integration = serializers.ListField(
        child=LabelCountField(), help_text="List of [integration, count] pairs"
    )
    samples = GoalEventSampleSerializer(many=True, help_text="A small sample of matching events")
    notes = serializers.ListField(
        child=serializers.CharField(), help_text="Caveats about the breakdown (sampling, attribution, etc.)"
    )


# --- suggest_conversion_goals ---


class SuggestConversionGoalsQuerySerializer(serializers.Serializer):
    top_n = serializers.IntegerField(required=False, default=10, help_text="Max candidates to return")
    min_count = serializers.IntegerField(
        required=False, default=50, help_text="Minimum 30d event count to be a candidate"
    )


class CandidateEventSerializer(serializers.Serializer):
    event_name = serializers.CharField(help_text="Name of the candidate event")
    last_30d_count = serializers.IntegerField(help_text="Count of this event in the last 30 days")
    distinct_users_30d = serializers.IntegerField(help_text="Distinct users who triggered the event in 30 days")
    pct_with_utm_source = serializers.FloatField(help_text="Percentage of events that carry a utm_source")
    pct_with_utm_campaign = serializers.FloatField(help_text="Percentage of events that carry a utm_campaign")
    top_utm_sources = serializers.ListField(child=LabelCountField(), help_text="List of [utm_source, count] pairs")
    is_already_a_goal = serializers.BooleanField(help_text="Whether this event is already configured as a goal")
    suggestion_score = serializers.FloatField(help_text="Ranking score (higher is a stronger candidate)")
    suggestion_reason = serializers.CharField(help_text="Human-readable rationale for the suggestion")


class EventSuggestionsResponseSerializer(serializers.Serializer):
    candidates = CandidateEventSerializer(many=True, help_text="Ranked candidate events for conversion goals")
    lookback_days = serializers.IntegerField(help_text="Lookback window in days used for the analysis")
    excluded_events_count = serializers.IntegerField(help_text="Number of system/autocaptured events excluded")


# --- suggest_utm_mappings ---


class SuggestUtmMappingsQuerySerializer(serializers.Serializer):
    min_event_count = serializers.IntegerField(
        required=False, default=10, help_text="Only suggest for raw values with >= this many events"
    )
    lookback_days = serializers.IntegerField(
        required=False,
        default=90,
        min_value=1,
        max_value=365,
        help_text="Days of history to inspect (1-365); defaults to 90",
    )


class SourceMappingSuggestionSerializer(serializers.Serializer):
    raw_utm_source = serializers.CharField(help_text="The raw utm_source value seen on events")
    suggested_target = serializers.CharField(help_text="Integration key it maps to")
    suggested_target_display_name = serializers.CharField(help_text="Human-readable name of the suggested integration")
    reason = serializers.CharField(help_text="Why this mapping is suggested")


class CampaignMappingSuggestionSerializer(serializers.Serializer):
    integration = serializers.CharField(help_text="Integration key the campaign values belong to")
    integration_display_name = serializers.CharField(help_text="Human-readable integration name")
    suggested_clean_name = serializers.CharField(help_text="Proposed canonical campaign name")
    raw_campaign_values = serializers.ListField(
        child=serializers.CharField(), help_text="Raw campaign values clustered under this clean name"
    )
    confidence = serializers.FloatField(help_text="Confidence score for the clustering (0-1)")
    method = serializers.CharField(help_text="Mapping method")
    reason = serializers.CharField(help_text="Why these campaign values were clustered together")


class RawUnmatchedSampleSerializer(serializers.Serializer):
    raw_utm_source = serializers.CharField(help_text="A raw utm_source value matching no integration")
    event_count = serializers.IntegerField(help_text="Number of events with this raw value in the window")
    suggested_integration = serializers.CharField(
        allow_null=True, help_text="Integration suggested by token match, if any"
    )


class CurrentMappingSerializer(serializers.Serializer):
    raw_utm_source = serializers.CharField(help_text="A utm_source value already mapped to an integration")
    target = serializers.CharField(help_text="Integration key it maps to")
    target_display_name = serializers.CharField(help_text="Human-readable name of the target integration")
    source = serializers.CharField(help_text="canonical or team_custom")  # type: ignore[assignment]


class CatalogueEntrySerializer(serializers.Serializer):
    raw_utm_source = serializers.CharField(help_text="A raw utm_source value seen in the window")
    event_count = serializers.IntegerField(help_text="Number of events with this value")
    matched_integration = serializers.CharField(
        allow_null=True, help_text="Integration this value exactly matches, if any"
    )
    matched_integration_display_name = serializers.CharField(
        allow_null=True, help_text="Human-readable name of the matched integration, if any"
    )
    suggested_integration = serializers.CharField(
        allow_null=True, help_text="Integration suggested by token match, if any"
    )


class UtmMappingSuggestionsResponseSerializer(serializers.Serializer):
    source_suggestions = SourceMappingSuggestionSerializer(
        many=True, help_text="Suggested custom_source_mappings entries"
    )
    campaign_suggestions = CampaignMappingSuggestionSerializer(
        many=True, help_text="Suggested campaign-name clusters (empty in v1)"
    )
    raw_unmatched_samples = RawUnmatchedSampleSerializer(
        many=True, help_text="All unmatched raw utm_source values worth reviewing"
    )
    full_utm_source_catalogue = CatalogueEntrySerializer(
        many=True, help_text="Every utm_source value seen in the window, matched or not"
    )
    current_mappings = CurrentMappingSerializer(
        many=True, help_text="Mappings already in effect (canonical + team_custom)"
    )
    total_unmatched_events_in_window = serializers.IntegerField(help_text="Total events with an unmatched utm_source")
    total_events_with_utm_in_window = serializers.IntegerField(help_text="Total events with any utm_source")
    lookback_days_used = serializers.IntegerField(help_text="Lookback window in days used for the analysis")
    notes = serializers.ListField(child=serializers.CharField(), help_text="Caveats and guidance about the suggestions")


# --- diagnose ---


class DiagnoseQuerySerializer(serializers.Serializer):
    source_type = serializers.CharField(
        required=False, default=None, allow_null=True, help_text="Optional integration filter"
    )
    include_conversion_goals = serializers.BooleanField(
        required=False, default=True, help_text="Whether to include the conversion-goal summary in the diagnostic"
    )
    attribution_lookback_days = serializers.IntegerField(
        required=False,
        default=7,
        min_value=1,
        max_value=365,
        help_text="Lookback window for attribution health (1-365 days); defaults to 7",
    )


class RecommendedActionSerializer(serializers.Serializer):
    title = serializers.CharField(help_text="Short title of the recommended action")
    detail = serializers.CharField(help_text="Detailed explanation of the action")
    severity = serializers.CharField(help_text="Action severity")
    target_tool = serializers.CharField(allow_null=True, help_text="Follow-up tool to call next, if any")


class UnmatchedUtmSampleSerializer(serializers.Serializer):
    raw_value = serializers.CharField(help_text="A raw utm_source value that doesn't match the integration exactly")
    event_count = serializers.IntegerField(help_text="Number of events with this raw value in the window")
    suggested_integration = serializers.CharField(
        allow_null=True, help_text="Integration suggested by token match, if any"
    )


class AttributionHealthEntrySerializer(serializers.Serializer):
    integration_key = serializers.CharField(help_text="Integration key (e.g. 'google', 'meta')")
    display_name = serializers.CharField(help_text="Human-readable integration name")
    events_with_utm_last_7d = serializers.IntegerField(help_text="Total events with any utm_source in the window")
    events_matched_last_7d = serializers.IntegerField(help_text="Events whose utm_source matched this integration")
    events_unmatched_likely_yours_last_7d = serializers.IntegerField(
        help_text="Events that look like this integration's but don't match exactly"
    )
    last_event_with_matching_utm_at = serializers.DateTimeField(
        allow_null=True, help_text="Timestamp of the most recent matched event"
    )
    matched_pct = serializers.FloatField(help_text="Percentage of UTM events matched to this integration")
    sample_unmatched_utm_sources = UnmatchedUtmSampleSerializer(
        many=True, help_text="Sample of likely-yours unmatched utm_source values"
    )


class IntegrationDiagnosticSerializer(serializers.Serializer):
    integration_key = serializers.CharField(help_text="Integration key (e.g. 'google', 'meta')")
    source_type = serializers.CharField(help_text="External data source type key (e.g. 'GoogleAds')")
    display_name = serializers.CharField(help_text="Human-readable integration name")
    overall_status = serializers.CharField(help_text="Per-integration status")
    diagnosis = serializers.CharField(help_text="Human-readable cross-domain diagnosis")
    data_source = DataSourceHealthEntrySerializer(
        allow_null=True, required=False, help_text="Data-source (sync) side health, or null if not connected"
    )
    attribution = AttributionHealthEntrySerializer(
        allow_null=True, required=False, help_text="Attribution (UTM events) side health, or null if no data"
    )
    recommended_actions = RecommendedActionSerializer(
        many=True, help_text="Recommended next steps for this integration"
    )


class MarketingDiagnosticResponseSerializer(serializers.Serializer):
    integrations = IntegrationDiagnosticSerializer(many=True, help_text="Per-integration cross-domain diagnostics")
    overall_status = serializers.CharField(help_text="healthy/degraded/broken/no_sources")
    summary = serializers.CharField(help_text="One-line plain-English summary of the diagnostic")
    conversion_goals = ConversionGoalsListResponseSerializer(
        allow_null=True, required=False, help_text="Conversion goal summary, when requested"
    )
    recommended_actions = RecommendedActionSerializer(
        many=True, help_text="Top global recommended actions across all integrations"
    )


class MarketingAnalyticsViewSet(TeamAndOrgViewSetMixin, GenericViewSet):
    # `marketing_analytics` is gated by the API scope of the same name and inherits
    # RBAC from `web_analytics` (see RESOURCE_INHERITANCE_MAP). Custom @action methods
    # below are not standard CRUD names, so each declares its own `required_scopes`;
    # actions without it stay session-only (not reachable via API key / OAuth / MCP).
    scope_object = "marketing_analytics"
    serializer_class = _FallbackSerializer
    permission_classes = [IsAuthenticated]

    @validated_request(
        query_serializer=UtmAuditQuerySerializer,
        responses={
            200: OpenApiResponse(response=UtmAuditResponseSerializer, description="UTM audit results"),
        },
        summary="Run UTM audit",
        description="Cross-reference campaigns with spend from ad platforms against pageview events with UTM parameters to identify tracking issues.",
    )
    @action(methods=["GET"], detail=False, url_path="utm_audit", required_scopes=["marketing_analytics:read"])
    def utm_audit(self, request: Request, *args, **kwargs) -> Response:
        date_from = request.validated_query_data["date_from"]
        date_to = request.validated_query_data["date_to"]

        try:
            audit_response = run_utm_audit(
                self.team, date_from=date_from, date_to=date_to, user=cast(User, request.user)
            )
            response_data = UtmAuditResponseSerializer(asdict(audit_response)).data
            return Response(response_data)
        except Exception:
            logger.exception("utm_audit_failed", team_id=self.team.pk, date_from=date_from, date_to=date_to)
            return Response(
                {"detail": "Failed to run UTM audit. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ConversionGoalsListResponseSerializer,
                description="Configured conversion goals with last-30d performance",
            ),
        },
        summary="List conversion goals",
        description="Read the configured conversion goals for the current project — each with its kind, target, last-30d count, integrated vs non-integrated split, and a misconfiguration flag. Read-only.",
    )
    @action(methods=["GET"], detail=False, url_path="conversion_goals", required_scopes=["marketing_analytics:read"])
    def conversion_goals(self, request: Request, *args, **kwargs) -> Response:
        try:
            response = async_to_sync(list_conversion_goals)(self.team, user=cast(User, request.user))
            return Response(ConversionGoalsListResponseSerializer(response.to_dict()).data)
        except Exception:
            logger.exception("list_conversion_goals_failed", team_id=self.team.pk)
            return Response(
                {"detail": "Failed to list conversion goals. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @validated_request(
        query_serializer=DataSourcesQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=DataSourceHealthResponseSerializer,
                description="Per-integration data-source (sync) health",
            ),
        },
        summary="List marketing data sources",
        description="Check the platform → data-warehouse side of every native marketing integration: connection state, sync recency, row counts, required-table status, and schema-mapping coverage. Read-only.",
    )
    @action(methods=["GET"], detail=False, url_path="data_sources", required_scopes=["marketing_analytics:read"])
    def list_data_sources(self, request: Request, *args, **kwargs) -> Response:
        source_type = request.validated_query_data["source_type"]
        try:
            response = async_to_sync(get_data_source_health)(self.team, source_type=source_type)
            return Response(DataSourceHealthResponseSerializer(response.to_dict()).data)
        except Exception:
            logger.exception("list_data_sources_failed", team_id=self.team.pk, source_type=source_type)
            return Response(
                {"detail": "Failed to list marketing data sources. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @validated_request(
        query_serializer=ExplainConversionGoalQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=GoalExplanationSerializer,
                description="Per-event breakdown of a single conversion goal",
            ),
        },
        summary="Explain a conversion goal",
        description="Break down a single conversion goal's events over a period by event name, utm_source, and matched integration, with a small sample of events. Read-only.",
    )
    @action(
        methods=["GET"], detail=False, url_path="explain_conversion_goal", required_scopes=["marketing_analytics:read"]
    )
    def explain_conversion_goal(self, request: Request, *args, **kwargs) -> Response:
        goal_id = request.validated_query_data["goal_id"]
        date_from = request.validated_query_data["date_from"]
        date_to = request.validated_query_data["date_to"]
        period = DateRange(date_from=date_from, date_to=date_to) if (date_from or date_to) else None
        try:
            response = async_to_sync(explain_conversion_goal)(self.team, goal_id, period=period)
            return Response(GoalExplanationSerializer(response.to_dict()).data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except Exception:
            logger.exception("explain_conversion_goal_failed", team_id=self.team.pk, goal_id=goal_id)
            return Response(
                {"detail": "Failed to explain conversion goal. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @validated_request(
        query_serializer=SuggestConversionGoalsQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=EventSuggestionsResponseSerializer,
                description="Ranked candidate events for conversion goals",
            ),
        },
        summary="Suggest conversion goals",
        description="Rank existing custom events as conversion-goal candidates by volume, UTM-tag coverage, and unique users, excluding system/autocaptured events. Read-only.",
    )
    @action(
        methods=["GET"], detail=False, url_path="suggest_conversion_goals", required_scopes=["marketing_analytics:read"]
    )
    def suggest_conversion_goals(self, request: Request, *args, **kwargs) -> Response:
        top_n = request.validated_query_data["top_n"]
        min_count = request.validated_query_data["min_count"]
        try:
            response = async_to_sync(suggest_conversion_goals)(self.team, top_n=top_n, min_count=min_count)
            return Response(EventSuggestionsResponseSerializer(response.to_dict()).data)
        except Exception:
            logger.exception("suggest_conversion_goals_failed", team_id=self.team.pk)
            return Response(
                {"detail": "Failed to suggest conversion goals. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @validated_request(
        query_serializer=SuggestUtmMappingsQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=UtmMappingSuggestionsResponseSerializer,
                description="Suggested utm_source → integration mappings",
            ),
        },
        summary="Suggest UTM source mappings",
        description="Detect unmatched utm_source values from recent events and propose custom_source_mappings entries, alongside the full utm_source catalogue and current mappings. Read-only.",
    )
    @action(
        methods=["GET"], detail=False, url_path="suggest_utm_mappings", required_scopes=["marketing_analytics:read"]
    )
    def suggest_utm_mappings(self, request: Request, *args, **kwargs) -> Response:
        min_event_count = request.validated_query_data["min_event_count"]
        lookback_days = request.validated_query_data["lookback_days"]
        try:
            response = async_to_sync(suggest_utm_mappings)(
                self.team, min_event_count=min_event_count, lookback_days=lookback_days
            )
            return Response(UtmMappingSuggestionsResponseSerializer(response.to_dict()).data)
        except Exception:
            logger.exception("suggest_utm_mappings_failed", team_id=self.team.pk)
            return Response(
                {"detail": "Failed to suggest UTM mappings. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @validated_request(
        query_serializer=DiagnoseQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=MarketingDiagnosticResponseSerializer,
                description="End-to-end marketing analytics diagnostic",
            ),
        },
        summary="Diagnose marketing analytics",
        description="Aggregate data-source sync health, UTM attribution health, and conversion-goal config into a single per-integration diagnostic with recommended actions. Read-only.",
    )
    @action(methods=["GET"], detail=False, url_path="diagnose", required_scopes=["marketing_analytics:read"])
    def diagnose(self, request: Request, *args, **kwargs) -> Response:
        source_type = request.validated_query_data["source_type"]
        include_conversion_goals = request.validated_query_data["include_conversion_goals"]
        attribution_lookback_days = request.validated_query_data["attribution_lookback_days"]
        try:
            response = async_to_sync(get_marketing_diagnostic)(
                self.team,
                source_type=source_type,
                include_conversion_goals=include_conversion_goals,
                attribution_lookback_days=attribution_lookback_days,
                user=cast(User, request.user),
            )
            return Response(MarketingDiagnosticResponseSerializer(response.to_dict()).data)
        except Exception:
            logger.exception("marketing_diagnose_failed", team_id=self.team.pk, source_type=source_type)
            return Response(
                {"detail": "Failed to run marketing diagnostic. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(methods=["POST"], detail=False, url_path="test_mapping")
    def test_mapping(self, request: Request, *args, **kwargs) -> Response:
        serializer = TestMappingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        table_id = serializer.validated_data["table_id"]
        source_map_data = serializer.validated_data["source_map"]

        try:
            table = DataWarehouseTable.objects.get(id=table_id, team=self.team)
        except DataWarehouseTable.DoesNotExist:
            return Response({"success": False, "error": "Table not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            source_type = _detect_source_type(table)
            source_map = SourceMap(**{k: v for k, v in source_map_data.items() if v})
            base_currency = getattr(self.team, "base_currency", DEFAULT_CURRENCY) or DEFAULT_CURRENCY

            context = QueryContext(
                date_range=None,
                team=self.team,
                base_currency=base_currency,
            )

            adapter_class = _get_adapter_class(source_type)
            config = ExternalConfig(
                table=table,
                source_map=source_map,
                source_type=source_type,
                source_id=str(table.id),
                schema_name="test_mapping",
            )

            adapter = adapter_class(config=config, context=context)

            # Call _build_select_columns() directly (not build_query()) so field
            # resolution errors propagate to the caller instead of being swallowed.
            select_columns = adapter._build_select_columns()
            from_expr = adapter._get_from()
            where_conditions = adapter._get_where_conditions()
            where_expr = None
            if where_conditions:
                where_expr = ast.And(exprs=where_conditions) if len(where_conditions) > 1 else where_conditions[0]

            query = ast.SelectQuery(select=select_columns, select_from=from_expr, where=where_expr)

            query.limit = ast.Constant(value=10)

            result = execute_hogql_query(query, self.team, user=cast(User, request.user))

            return Response(
                {
                    "success": True,
                    "row_count": len(result.results) if result.results else 0,
                    "columns": result.columns or [],
                    "sample_data": (result.results or [])[:10],
                    "hogql": query.to_hogql(),
                }
            )

        except Exception as e:
            logger.exception("Test mapping failed", error=str(e))
            return Response(
                {"success": False, "error": "Failed to test mapping. Check server logs for details."},
                status=status.HTTP_400_BAD_REQUEST,
            )


def _detect_source_type(table: DataWarehouseTable) -> str:
    if hasattr(table, "external_data_source") and table.external_data_source:
        return table.external_data_source.source_type or "BigQuery"

    platform = map_url_to_provider(table.url_pattern)
    return platform if platform != "BlushingHog" else "self_managed"


def _get_adapter_class(source_type: str) -> type:
    adapter_class = MarketingSourceFactory._adapter_registry.get(source_type)
    if adapter_class:
        return adapter_class

    return SelfManagedAdapter
