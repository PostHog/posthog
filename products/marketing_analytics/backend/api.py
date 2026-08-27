import uuid
from dataclasses import asdict
from functools import reduce
from operator import or_
from typing import Any, Optional, cast

from django.core.cache import cache
from django.db import transaction

import structlog
from asgiref.sync import async_to_sync
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from pydantic import (
    BaseModel,
    ConfigDict,
    RootModel as PydanticRootModel,
    TypeAdapter,
    ValidationError as PydanticValidationError,
    create_model,
)
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from posthog.schema import ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3, DateRange, SourceMap

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.api.documentation import _FallbackSerializer
from posthog.api.mixins import validated_request
from posthog.api.project import capture_team_config_diff
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import DEFAULT_CURRENCY, Team
from posthog.models.team.team_marketing_analytics_config import TeamMarketingAnalyticsConfig
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

from products.marketing_analytics.backend.hogql_queries.adapters.base import ExternalConfig, QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory
from products.marketing_analytics.backend.hogql_queries.adapters.self_managed import SelfManagedAdapter
from products.marketing_analytics.backend.hogql_queries.constants import CONVERSION_GOAL_KIND_CHOICES
from products.marketing_analytics.backend.hogql_queries.utils import map_url_to_provider
from products.marketing_analytics.backend.services.conversion_goals_inspector import (
    explain_conversion_goal,
    list_conversion_goals,
)
from products.marketing_analytics.backend.services.data_source_health import get_data_source_health
from products.marketing_analytics.backend.services.event_suggestions import suggest_conversion_goals
from products.marketing_analytics.backend.services.mapping_suggester import suggest_utm_mappings
from products.marketing_analytics.backend.services.marketing_diagnostic import get_marketing_diagnostic
from products.marketing_analytics.backend.services.setup_plan import get_setup_plan
from products.marketing_analytics.backend.services.setup_types import (
    APPLICABLE_OPS,
    NAVIGATE_OPS,
    AddCampaignNameMapping,
    AddCustomSourceMapping,
    ApplyOp,
    CreateConversionGoal,
    DeleteConversionGoal,
    RemoveCampaignNameMapping,
    RemoveCustomSourceMapping,
    SetCampaignFieldPreference,
    UpdateConversionGoal,
)
from products.marketing_analytics.backend.services.types import SUGGESTED_ACTION_CHOICES, UTM_ISSUE_KIND_CHOICES
from products.marketing_analytics.backend.services.utm_audit import run_utm_audit
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

logger = structlog.get_logger(__name__)


def _setup_enabled(request: Request, team: Team) -> bool:
    """Evaluate the Setup flag once per request.

    Evaluated for the requesting person, because the flag's release conditions target
    people and the frontend renders the Setup tab off that same per-person answer.
    Evaluating it against anything else is how the tab ends up sitting on top of an
    endpoint that 404s. The organization group still goes along, so a group release
    condition matches too. Cached on the request because a second call in the same one
    would fire a redundant `$feature_flag_called`.
    """
    cached = getattr(request, "_ma_setup_flag", None)
    if cached is not None:
        return cached
    person_properties = {}
    email = getattr(request.user, "email", None)
    if email:
        person_properties["email"] = email
    enabled = feature_enabled_or_false(
        "marketing-analytics-setup",
        # Service credentials authenticate as a synthetic user with no person behind them;
        # the team UUID keeps the call well-formed, and a person condition won't match it.
        getattr(request.user, "distinct_id", None) or str(team.uuid),
        groups={"organization": str(team.organization.id)},
        person_properties=person_properties,
        group_properties={"organization": {"id": str(team.organization.id)}},
    )
    request._ma_setup_flag = enabled  # type: ignore[attr-defined]
    return enabled


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


class UtmAlternativeSourceSerializer(serializers.Serializer):
    utm_source = serializers.CharField(help_text="A utm_source value found on this campaign's pageviews")
    event_count = serializers.IntegerField(help_text="Number of pageview events with this utm_source")


class UtmIssueSerializer(serializers.Serializer):
    field = serializers.CharField(help_text="The UTM field with the issue (e.g. utm_campaign, utm_source)")
    severity = serializers.ChoiceField(choices=["error", "warning"], help_text="Issue severity level")
    # `kind` collides with other enums in drf-spectacular, so it carries a stable name via
    # ENUM_NAME_OVERRIDES ("UtmIssueKindEnum") rather than being flattened to a plain string —
    # consumers get the five values as a union instead of having to restate them.
    kind = serializers.ChoiceField(
        choices=UTM_ISSUE_KIND_CHOICES,
        help_text="Which kind of UTM problem this campaign has",
    )
    message = serializers.CharField(
        help_text="Human-readable headline; the frontend composes richer text from the fields below"
    )
    alternative_sources = UtmAlternativeSourceSerializer(
        many=True, help_text="utm_source values actually found on this campaign's pageviews, ordered by event count"
    )
    shared_with_integrations = serializers.ListField(
        child=serializers.CharField(),
        help_text="Other integrations whose campaigns share this campaign's name (name_collision only)",
    )
    missing_source_count = serializers.IntegerField(
        help_text="Pageviews that matched this campaign but carried no utm_source, on any issue kind"
    )
    suggested_actions = serializers.ListField(
        child=serializers.ChoiceField(choices=SUGGESTED_ACTION_CHOICES),
        help_text=(
            "Recommended remediations, most-recommended first. fix_platform_urls cures the tagging "
            "bug itself; the others are workarounds that leave the bad URLs in place."
        ),
    )
    mapping_candidate = serializers.CharField(
        allow_blank=True,
        help_text=(
            "The orphaned utm_campaign value that looks like a typo of this campaign, when one was "
            "found confidently. Set only alongside add_campaign_name_mapping; empty otherwise, "
            "including when several candidates tie and picking one could misattribute spend."
        ),
    )


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
    conversion_goal_id = serializers.CharField(
        help_text="Id of the goal. Pass this to the explain, update and delete endpoints."
    )
    name = serializers.CharField(help_text="Display name of the conversion goal")
    # `kind` collides with other enums in drf-spectacular, so it carries a stable name via
    # ENUM_NAME_OVERRIDES ("ConversionGoalKindEnum") — a plain CharField would leave consumers
    # reading the valid values out of this help text.
    kind = serializers.ChoiceField(
        choices=CONVERSION_GOAL_KIND_CHOICES,
        help_text="Goal type: EventsNode (PostHog event), ActionsNode (PostHog action), or DataWarehouseNode (external table)",
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


# --- conversion goal writes ---


_CONVERSION_GOAL_ADAPTER: TypeAdapter[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3] = (
    TypeAdapter(ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3)
)


_SUM_MATHS = frozenset({"sum"})


def _revenue_goal_error(goal: dict[str, Any]) -> str | None:
    """Why this goal can't claim to carry revenue, or None if it can.

    `counts_as_revenue` on its own changes nothing in the query: `get_select_field`
    only sums when `math` is a sum type, and `_build_sum_select` returns a literal 0
    without a `math_property`. So the flag alone produces a ROAS column that is either
    a conversion count divided by spend, or a row of zeros — both of which look like
    answers. Nothing validated this before, on any of the three write paths.
    """
    if not goal.get("counts_as_revenue"):
        return None
    math = str(goal.get("math") or "")
    if math not in _SUM_MATHS:
        return f"counts_as_revenue needs math='sum' so the amount is summed rather than counted; got {math or 'none'}."
    if not goal.get("math_property"):
        return "counts_as_revenue needs math_property naming the field that holds the amount."
    return None


class ConversionGoalWrittenList(PydanticRootModel):
    """List wrapper for OpenAPI schema generation - the response carries every configured goal."""

    root: list[ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3]


class ConversionGoal(PydanticRootModel):
    """Wrapper for OpenAPI schema generation - one goal, in any of the three node shapes."""

    root: ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3


def _partial_goal_model(model: type[BaseModel]) -> type[BaseModel]:
    """The same goal shape with every field optional, for the update request body.

    Update merges what you send into the stored goal, so the request is a patch, not a whole goal.
    Annotating it with the full model generates a type whose members all require an id, a name and a
    schema map, making the endpoint's own documented call — `{"goal": {"counts_as_customer": true}}` —
    a type error that a client can only get past by casting. Derived from the real model so a new
    field can't be forgotten here.
    """
    return create_model(  # type: ignore[call-overload]
        f"Partial{model.__name__}",
        __config__=ConfigDict(extra="forbid"),
        __doc__=f"{model.__name__} with every field optional - the fields you send are merged into the stored goal.",
        **{
            name: (Optional[field.annotation], None if name != "kind" else field.default)
            for name, field in model.model_fields.items()
        },
    )


def _conversion_goal_patch_model() -> Any:
    """Wrapper for OpenAPI schema generation - the fields to change on one existing goal.

    Built rather than declared: the members are derived from the real goal models, which a class-body
    annotation can't name.
    """
    partials = [
        _partial_goal_model(model) for model in (ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3)
    ]
    union = reduce(or_, partials)
    return create_model("ConversionGoalPatch", __base__=PydanticRootModel, root=(union, ...))


ConversionGoalPatch = _conversion_goal_patch_model()


@extend_schema_field(ConversionGoal)  # type: ignore[arg-type]
class ConversionGoalField(serializers.JSONField):
    def to_internal_value(self, data: Any) -> dict:
        value = super().to_internal_value(data)
        # JSONField accepts any JSON value; a non-object goal would 500 at the dict() call downstream
        if not isinstance(value, dict):
            raise serializers.ValidationError("goal must be a JSON object.")
        return value


@extend_schema_field(ConversionGoalPatch)
class ConversionGoalPatchField(ConversionGoalField):
    pass


@extend_schema_field(ConversionGoalWrittenList)  # type: ignore[arg-type]
class ConversionGoalListField(serializers.JSONField):
    pass


_GOAL_MODEL_BY_KIND = {
    model.model_fields["kind"].default: model.__name__
    for model in (ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3)
}


def _normalized_goal_name(name: Any) -> str | None:
    """Goal names as compared for uniqueness — they become SQL column aliases downstream."""
    return name.strip().casefold() if isinstance(name, str) else None


def _readable_pydantic_errors(error: PydanticValidationError, kind: Any = None) -> list[str]:
    """Pydantic reports one error per union member, which is noise. Keep the field and the message.

    Errors are preferred from the member matching the payload's `kind`: otherwise the first member
    wins per field, so a data warehouse payload could be told about the events node's requirements
    for a field it did send correctly.
    """
    preferred_model = _GOAL_MODEL_BY_KIND.get(kind)
    seen: dict[str, str] = {}
    for detail in sorted(error.errors(), key=lambda d: str(d["loc"][:1]) != str((preferred_model,))):
        field = ".".join(str(part) for part in detail["loc"] if not str(part).startswith("ConversionGoalFilter"))
        seen.setdefault(field or "goal", detail["msg"])
    return [f"{field}: {message}" for field, message in seen.items()]


class ConversionGoalWriteSerializer(serializers.Serializer):
    goal = ConversionGoalField(
        help_text=(
            "The conversion goal. Must match one of the ConversionGoalFilter shapes: an events node, an actions "
            "node or a data warehouse node. conversion_goal_id is assigned by the server and any value sent "
            "is ignored."
        )
    )


class ConversionGoalUpdateSerializer(serializers.Serializer):
    """Separate from create: the body is a patch, so the documented partial has to type-check."""

    goal = ConversionGoalPatchField(
        help_text=(
            "The fields to change, merged into the stored goal — anything you leave out is kept, and the goal "
            "keeps its position in the list. schema_map is merged key by key. The merged result must still match "
            "one of the ConversionGoalFilter shapes. Send `kind` only to change the goal's shape, in which case "
            "the goal is replaced rather than merged and the whole new shape is required. conversion_goal_id "
            "comes from the URL and any value sent is ignored."
        )
    )


class ConversionGoalWriteResponseSerializer(serializers.Serializer):
    goal = ConversionGoalField(help_text="The goal as stored after the write")
    conversion_goals = ConversionGoalListField(help_text="Every configured goal after the write, in display order")


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
    conversion_goal_id = serializers.CharField(
        required=True,
        help_text=("conversion_goal_id of the goal to explain, as returned by the conversion_goals list endpoint."),
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
    conversion_goal_id = serializers.CharField(help_text="conversion_goal_id of the explained goal")
    goal_name = serializers.CharField(help_text="Display name of the conversion goal")
    kind = serializers.ChoiceField(
        choices=CONVERSION_GOAL_KIND_CHOICES,
        help_text="Goal type: EventsNode (PostHog event), ActionsNode (PostHog action), or DataWarehouseNode (external table)",
    )
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
    event_count_30d = serializers.IntegerField(
        help_text="Events carrying this raw utm_source in the window. Suggestions are ordered by it."
    )


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
    event_count_30d = serializers.IntegerField(
        help_text="Events across every raw value folded into this suggestion. Suggestions are ordered by it."
    )


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
        many=True,
        help_text=(
            "campaign_name_mappings entries for orphaned utm_campaign values that fuzzy-match a real "
            "campaign. Near-ties are withheld, so an absent campaign may still be mappable by hand."
        ),
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
    events_matched_paid_last_7d = serializers.IntegerField(
        help_text=(
            "Of the matched events, how many look paid: a cost-bearing utm_medium (cpc, cpm, cpv, cpa, ppc, "
            "retargeting, or anything starting with 'paid') or a gclid/gad_source click id."
        )
    )
    events_matched_tagged_medium_last_7d = serializers.IntegerField(
        help_text=(
            "Of the matched events, how many carry any utm_medium. Zero paid with a non-zero count here means "
            "the traffic is tagged and organic; both zero means the team doesn't tag medium, which says nothing."
        )
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


class SetupPlanQuerySerializer(serializers.Serializer):
    date_from = serializers.CharField(
        required=False,
        default="-30d",
        help_text="Window for campaign spend and the UTM catalogue, as a relative range (e.g. '-30d'); defaults to -30d",
    )
    refresh = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Re-run every check instead of serving a recent result. Use right after changing something.",
    )


# The plan is roughly six ClickHouse queries deep, one of which unions every ad
# adapter, so moving between Setup sections must not re-run it. Short enough that an
# explicit rescan a minute later is genuinely fresh, and `refresh=true` skips it
# outright for the "I just changed something" case.
_SETUP_PLAN_CACHE_SECONDS = 60


def _setup_plan_version_key(team_id: int) -> str:
    return f"marketing_analytics:setup_plan_version:{team_id}"


def _setup_plan_cache_key(team_id: int, user_id: int, date_from: str) -> str:
    # Keyed on the window because the same team asking about a different range is a
    # different question, and on the user because the plan is built from HogQL run as
    # them — `execute_hogql_query(..., user=user)` applies warehouse access control, so
    # two users can legitimately see different campaigns and spend. The version segment
    # is what makes invalidation possible; see `_invalidate_setup_plan_cache`.
    version = cache.get(_setup_plan_version_key(team_id), 0)
    return f"marketing_analytics:setup_plan:{team_id}:{version}:{user_id}:{date_from}"


def _invalidate_setup_plan_cache(team_id: int) -> None:
    """Orphan every cached plan for a team by bumping its version.

    A bump rather than a delete because entries are keyed by window and by user as well,
    and we know neither set. Bumping also covers everyone at once, which is what an
    applied change calls for — the config it was built from is gone for all of them.
    Orphaned entries cost nothing: they age out on their own TTL and nothing can reach
    them again.
    """
    key = _setup_plan_version_key(team_id)
    try:
        cache.incr(key)
    except ValueError:
        # No counter yet. `None` = no expiry: a version that aged out would start
        # serving the pre-bump entries again, though only until their own TTL runs out.
        cache.set(key, 1, None)


class SuggestionSerializer(serializers.Serializer):
    id = serializers.CharField(
        help_text="Stable identifier for this finding. Deterministic across scans, so clients can dedupe and remember dismissals by it."
    )
    kind = serializers.CharField(help_text="Suggestion kind, e.g. connect_source / add_source_mapping")
    # Shadows `Field.source`, DRF's attribute-mapping name. Declaring it is fine — the
    # field is read out of the dict by its own name — but mypy sees the base annotation.
    source = serializers.CharField(  # type: ignore[assignment]
        help_text="'deterministic' or 'ai' — how this suggestion was produced"
    )
    severity = serializers.CharField(help_text="error/warning/info")
    confidence = serializers.FloatField(help_text="0-1. Never 1.0: these are inferences, not proofs.")
    title = serializers.CharField(help_text="Short imperative title, e.g. 'Connect Meta Ads'")
    evidence = serializers.CharField(
        help_text="The concrete numbers behind the suggestion, so a user can sanity-check it without taking it on faith"
    )
    unlocks = serializers.ListField(
        child=serializers.CharField(),
        help_text="Capabilities this unblocks: cost, attribution, roas, cac",
    )
    # DRF has no discriminated-union field and fighting drf-spectacular for one isn't
    # worth it. The shape is the `ApplyOp` union in `services/setup_types.py`, which is
    # where the apply endpoint validates it with a Pydantic TypeAdapter.
    apply = serializers.JSONField(
        allow_null=True,
        help_text=(
            "The operation that applies this suggestion, or null when there's nothing to automate. "
            "An object with an 'op' discriminator — see the ApplyOp union in setup_types. "
            "Pass it verbatim to apply_setup_ops; never hand-craft one."
        ),
    )
    also_recommended = serializers.ListField(
        child=serializers.JSONField(),
        help_text=(
            "Advice shown alongside the action. Mapping suggestions always carry a 'fix_platform_urls' entry, "
            "because a mapping is a workaround and correcting the ad platform's tracking template is the real fix."
        ),
    )
    safe_to_batch = serializers.BooleanField(
        help_text="True only for high-confidence, reversible operations — what an 'apply all safe' button may include"
    )
    rank_score = serializers.FloatField(help_text="Ranking score; higher first. Unblocking actions dominate.")
    integration = serializers.CharField(allow_null=True, help_text="Integration this concerns, if any")
    deep_link = serializers.CharField(allow_null=True, help_text="In-app URL to resolve this manually, if any")
    docs_url = serializers.CharField(allow_null=True, help_text="Documentation link, if any")
    spend_at_risk = serializers.FloatField(help_text="Ad spend currently mis- or un-attributed because of this")
    event_volume = serializers.IntegerField(help_text="Events affected in the window")


class CapabilityReadinessSerializer(serializers.Serializer):
    capability = serializers.CharField(help_text="cost/attribution/roas/cac")
    status = serializers.CharField(help_text="unlocked/partial/blocked")
    explanation = serializers.CharField(help_text="Why it's in that state, in plain English")
    blocked_by = serializers.ListField(
        child=serializers.CharField(),
        help_text="Suggestion ids that unblock this capability — the link from a blocked metric to its fixes",
    )


class SetupPlanResponseSerializer(serializers.Serializer):
    suggestions = SuggestionSerializer(many=True, help_text="Ranked suggestions, most important first")
    readiness = CapabilityReadinessSerializer(
        many=True, help_text="Per-capability readiness, with the suggestions blocking each"
    )
    degraded = serializers.ListField(
        child=serializers.CharField(),
        help_text=(
            "Sub-services that failed. Their suggestions are missing, so do NOT present the plan as a "
            "complete clean bill of health when this is non-empty."
        ),
    )
    truncated = serializers.BooleanField(
        help_text=(
            "True when the campaign or UTM queries hit their row caps. Rates and totals are then top-N "
            "subtotals — present them as approximate rather than exact."
        )
    )
    summary = serializers.CharField(help_text="One-line summary of the plan")


_SETUP_OPS_ADAPTER: TypeAdapter[list[ApplyOp]] = TypeAdapter(list[ApplyOp])

# Applicable ops the apply endpoint doesn't implement yet. `set_source_column_mapping`
# and `set_customer_analytics_event` both need work that belongs with their own
# features — the former an inverse for "this table had no mapping at all", the latter
# the project-admin check its fields carry. Rejecting them loudly beats silently
# accepting an op that does nothing.
_UNIMPLEMENTED_OPS = frozenset({"set_source_column_mapping", "set_customer_analytics_event"})


def _apply_setup_op(config: TeamMarketingAnalyticsConfig, op: ApplyOp) -> dict[str, Any] | None:
    """Apply one op in place and return the op that reverses it, or None if it was a
    no-op (re-applying an existing mapping, for instance — idempotent for MCP retries).

    Mutations go through the model's property setters so the existing validators run.
    """
    if isinstance(op, AddCustomSourceMapping):
        mappings = {key: list(values) for key, values in (config.custom_source_mappings or {}).items()}
        existing = mappings.setdefault(op.integration, [])
        if op.raw_utm_source in existing:
            return None
        existing.append(op.raw_utm_source)
        config.custom_source_mappings = mappings
        return RemoveCustomSourceMapping(integration=op.integration, raw_utm_source=op.raw_utm_source).model_dump(
            mode="json"
        )

    if isinstance(op, RemoveCustomSourceMapping):
        mappings = {key: list(values) for key, values in (config.custom_source_mappings or {}).items()}
        existing = mappings.get(op.integration, [])
        if op.raw_utm_source not in existing:
            return None
        existing.remove(op.raw_utm_source)
        if not existing:
            mappings.pop(op.integration, None)
        else:
            mappings[op.integration] = existing
        config.custom_source_mappings = mappings
        return AddCustomSourceMapping(integration=op.integration, raw_utm_source=op.raw_utm_source).model_dump(
            mode="json"
        )

    if isinstance(op, SetCampaignFieldPreference):
        preferences = {key: dict(value) for key, value in (config.campaign_field_preferences or {}).items()}
        # Absent means "campaign_name" (the documented default), so restoring the
        # default explicitly is equivalent to restoring absence.
        previous = preferences.get(op.integration, {}).get("match_field", "campaign_name")
        if previous == op.match_field:
            return None
        preferences[op.integration] = {"match_field": op.match_field}
        config.campaign_field_preferences = preferences
        return SetCampaignFieldPreference(integration=op.integration, match_field=previous).model_dump(mode="json")

    if isinstance(op, AddCampaignNameMapping):
        # Named apart from `mappings` above: this one is two levels deep
        # (integration -> clean name -> raw values), and sharing the name would hide that.
        campaign_mappings = _clone_campaign_mappings(config)
        per_integration = campaign_mappings.setdefault(op.integration, {})
        existing = per_integration.setdefault(op.clean_name, [])
        added = [value for value in op.raw_values if value not in existing]
        if not added:
            return None
        existing.extend(added)
        config.campaign_name_mappings = campaign_mappings
        # Undo removes only what this op added, so a value that was already mapped
        # survives the undo.
        return RemoveCampaignNameMapping(
            integration=op.integration, clean_name=op.clean_name, raw_values=added
        ).model_dump(mode="json")

    if isinstance(op, RemoveCampaignNameMapping):
        campaign_mappings = _clone_campaign_mappings(config)
        per_integration = campaign_mappings.get(op.integration, {})
        existing = per_integration.get(op.clean_name, [])
        removed = [value for value in op.raw_values if value in existing]
        if not removed:
            return None
        per_integration[op.clean_name] = [value for value in existing if value not in removed]
        if not per_integration[op.clean_name]:
            per_integration.pop(op.clean_name, None)
        if not per_integration:
            campaign_mappings.pop(op.integration, None)
        config.campaign_name_mappings = campaign_mappings
        return AddCampaignNameMapping(
            integration=op.integration, clean_name=op.clean_name, raw_values=removed
        ).model_dump(mode="json")

    if isinstance(op, CreateConversionGoal):
        goals = list(config.conversion_goals)
        goal = dict(op.goal)
        if op.restore and goal.get("conversion_goal_id"):
            if any(existing.get("conversion_goal_id") == goal["conversion_goal_id"] for existing in goals):
                raise serializers.ValidationError({"ops": "That conversion goal already exists."})
        else:
            goal["conversion_goal_id"] = str(uuid.uuid4())
        try:
            validated = _CONVERSION_GOAL_ADAPTER.validate_python(goal)
        except PydanticValidationError as e:
            raise serializers.ValidationError({"ops": _readable_pydantic_errors(e)})
        revenue_error = _revenue_goal_error(goal)
        if revenue_error:
            raise serializers.ValidationError({"ops": revenue_error})
        stored = validated.model_dump(exclude_none=True, mode="json")
        goals.append(stored)
        config._conversion_goals = goals
        return DeleteConversionGoal(conversion_goal_id=stored["conversion_goal_id"]).model_dump(mode="json")

    if isinstance(op, UpdateConversionGoal):
        goals = list(config.conversion_goals)
        index = _index_of_goal(goals, op.conversion_goal_id)
        before = dict(goals[index])
        merged = {**before, **op.patch}
        try:
            validated = _CONVERSION_GOAL_ADAPTER.validate_python(merged)
        except PydanticValidationError as e:
            raise serializers.ValidationError({"ops": _readable_pydantic_errors(e)})
        # The merged goal, not the patch: flipping `counts_as_revenue` on a goal that
        # counts rows is exactly the state to reject, and the patch alone can't see it.
        revenue_error = _revenue_goal_error(merged)
        if revenue_error:
            raise serializers.ValidationError({"ops": revenue_error})
        goals[index] = validated.model_dump(exclude_none=True, mode="json")
        config._conversion_goals = goals
        # Undo restores only the keys this patch touched, so a concurrent change to
        # another field isn't reverted along with it.
        return UpdateConversionGoal(
            conversion_goal_id=op.conversion_goal_id,
            patch={key: before.get(key) for key in op.patch},
        ).model_dump(mode="json")

    if isinstance(op, DeleteConversionGoal):
        goals = list(config.conversion_goals)
        removed = goals.pop(_index_of_goal(goals, op.conversion_goal_id))
        config._conversion_goals = goals
        # `restore=True` keeps the original id so the undo puts back the same goal
        # rather than a copy. Position is not restored — goals are keyed by id and
        # name, not order.
        return CreateConversionGoal(goal=removed, restore=True).model_dump(mode="json")

    raise serializers.ValidationError({"ops": f"'{op.op}' is not a supported operation."})


def _clone_campaign_mappings(config: TeamMarketingAnalyticsConfig) -> dict[str, dict[str, list[str]]]:
    return {
        integration: {clean: list(raws) for clean, raws in per_integration.items()}
        for integration, per_integration in (config.campaign_name_mappings or {}).items()
    }


def _index_of_goal(goals: list[dict], conversion_goal_id: str) -> int:
    for index, goal in enumerate(goals):
        if goal.get("conversion_goal_id") == conversion_goal_id:
            return index
    raise NotFound(f"No conversion goal with id '{conversion_goal_id}'.")


class ApplySetupOpsSerializer(serializers.Serializer):
    ops = serializers.ListField(
        child=serializers.JSONField(),
        allow_empty=False,
        help_text=(
            "Operations to apply, in order. Send `apply` payloads returned verbatim by setup_plan — "
            "never hand-craft one. Navigate-only ops (open_oauth, open_source_wizard, open_settings, "
            "fix_platform_urls) are rejected: they describe something a browser or a human does."
        ),
    )
    # Shadows `Field.source`, DRF's attribute-mapping name — same as on SuggestionSerializer.
    source = serializers.ChoiceField(  # type: ignore[assignment]
        choices=["setup_tab", "apply_all_safe", "mcp"],
        required=False,
        default="setup_tab",
        help_text="Where the request came from, recorded in the activity log",
    )


class ApplySetupOpsResponseSerializer(serializers.Serializer):
    applied = serializers.ListField(child=serializers.JSONField(), help_text="The operations that were applied")
    undo_ops = serializers.ListField(
        child=serializers.JSONField(),
        help_text=(
            "Operations that reverse this batch, in the order they should be sent. Computed server-side "
            "from the pre-change state — POST them back to undo."
        ),
    )
    marketing_analytics_config = serializers.JSONField(help_text="The config as it now stands")


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
        request_serializer=ConversionGoalWriteSerializer,
        responses={
            201: OpenApiResponse(response=ConversionGoalWriteResponseSerializer, description="The goal as created"),
            400: OpenApiResponse(description="The goal does not match any conversion goal shape"),
            403: OpenApiResponse(description="Requires project admin access"),
        },
        summary="Create conversion goal",
        description="Add one conversion goal to the project. The server assigns conversion_goal_id and appends the goal to the end of the list, leaving existing goals untouched.",
    )
    @action(
        methods=["POST"],
        detail=False,
        url_path="conversion_goals/create",
        required_scopes=["marketing_analytics:write"],
    )
    def create_conversion_goal(self, request: Request, *args, **kwargs) -> Response:
        self._require_project_admin()
        goal = dict(request.validated_data["goal"])
        goal["conversion_goal_id"] = str(uuid.uuid4())

        with transaction.atomic():
            config = self._locked_config()
            previous = list(config.conversion_goals)
            goals = list(previous)
            goals.append(self._validated_goal(goal, existing=goals))
            self._store_goals(config, goals, previous=previous)

        return Response(
            {"goal": goals[-1], "conversion_goals": goals},
            status=status.HTTP_201_CREATED,
        )

    @validated_request(
        request_serializer=ConversionGoalUpdateSerializer,
        responses={
            200: OpenApiResponse(response=ConversionGoalWriteResponseSerializer, description="The goal as updated"),
            400: OpenApiResponse(description="The resulting goal does not match any conversion goal shape"),
            403: OpenApiResponse(description="Requires project admin access"),
            404: OpenApiResponse(description="No goal with that conversion_goal_id"),
        },
        summary="Update conversion goal",
        description=(
            "Change one conversion goal in place. Fields you send are merged into the stored goal, the rest are "
            "kept, and the goal keeps its position in the list. Sending a different `kind` replaces the goal "
            "instead, since the shapes don't share their fields."
        ),
    )
    @action(
        methods=["PATCH"],
        detail=False,
        url_path="conversion_goals/(?P<conversion_goal_id>[^/.]+)/update",
        required_scopes=["marketing_analytics:write"],
    )
    def update_conversion_goal(self, request: Request, *args, **kwargs) -> Response:
        self._require_project_admin()
        conversion_goal_id = kwargs["conversion_goal_id"]
        patch = dict(request.validated_data["goal"])

        with transaction.atomic():
            config = self._locked_config()
            previous = list(config.conversion_goals)
            goals = list(previous)
            index = self._index_of(goals, conversion_goal_id)

            merged = self._merged_goal(goals[index], patch, conversion_goal_id)
            goals[index] = self._validated_goal(merged, existing=goals, ignore_index=index)
            self._store_goals(config, goals, previous=previous)

        return Response({"goal": goals[index], "conversion_goals": goals})

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response=ConversionGoalWriteResponseSerializer, description="The goals left after the delete"
            ),
            403: OpenApiResponse(description="Requires project admin access"),
            404: OpenApiResponse(description="No goal with that conversion_goal_id"),
        },
        summary="Delete conversion goal",
        description="Remove one conversion goal from the project, leaving the others in place.",
    )
    @action(
        methods=["DELETE"],
        detail=False,
        url_path="conversion_goals/(?P<conversion_goal_id>[^/.]+)/delete",
        required_scopes=["marketing_analytics:write"],
    )
    def delete_conversion_goal(self, request: Request, *args, **kwargs) -> Response:
        self._require_project_admin()
        conversion_goal_id = kwargs["conversion_goal_id"]

        with transaction.atomic():
            config = self._locked_config()
            previous = list(config.conversion_goals)
            goals = list(previous)
            removed = goals.pop(self._index_of(goals, conversion_goal_id))
            self._store_goals(config, goals, previous=previous)

        return Response({"goal": removed, "conversion_goals": goals})

    def _require_project_admin(self) -> None:
        # The settings PATCH path puts these fields behind ADMIN, so these endpoints have to clear
        # the same bar or they route around it. RBAC alone doesn't: `check_access_level_for_object`
        # is permissive without the ACCESS_CONTROL feature. Either check satisfies.
        if self.user_access_control.access_controls_supported:
            if self.user_access_control.check_access_level_for_object(self.team, "admin"):
                return

        level = self.user_permissions.team(self.team).effective_membership_level
        if level is None or level < OrganizationMembership.Level.ADMIN:
            raise PermissionDenied("You need admin access to this project to modify conversion goals.")

    def _locked_config(self) -> TeamMarketingAnalyticsConfig:
        """Take a row lock so concurrent single-goal writes can't clobber each other."""
        config = self.team.marketing_analytics_config
        return TeamMarketingAnalyticsConfig.objects.select_for_update().get(pk=config.pk)

    def _validated_goal(self, goal: dict, existing: list[Any], ignore_index: int | None = None) -> dict[str, Any]:
        try:
            validated = _CONVERSION_GOAL_ADAPTER.validate_python(goal)
        except PydanticValidationError as e:
            raise serializers.ValidationError({"goal": _readable_pydantic_errors(e, goal.get("kind"))})

        name = goal.get("conversion_goal_name")
        # Normalized, because names differing only in case collide as SQL column aliases.
        # Storage keeps the name as sent.
        normalized = _normalized_goal_name(name)
        for index, other in enumerate(existing):
            # A malformed sibling can't collide by name, and failing this write over a row it never
            # touches is the trade `_store_goals` already refuses to make.
            if not isinstance(other, dict):
                continue
            if index != ignore_index and _normalized_goal_name(other.get("conversion_goal_name")) == normalized:
                raise serializers.ValidationError({"goal": f"A conversion goal named '{name}' already exists."})

        stored = validated.model_dump(exclude_none=True, mode="json")
        # `name` is optional on the schema but required by the legacy full-config PATCH the settings
        # UI still sends, and the UI never exposes it, so a goal stored without one can't be repaired
        # from the product. Mirrored rather than defaulted, or a rename leaves a stale `name`.
        stored["name"] = stored["conversion_goal_name"]
        return stored

    def _merged_goal(self, stored: dict, patch: dict, conversion_goal_id: str) -> dict:
        """Apply a partial goal onto the stored one, per the endpoint's documented merge semantics."""
        if not isinstance(stored, dict):
            # `_index_of` tolerates a non-dict row via `.get`, so don't blow up with a TypeError here.
            raise serializers.ValidationError(
                {"goal": "The stored conversion goal is malformed and cannot be updated."}
            )

        # The models are `extra="forbid"`, so a merge leaves old-kind keys behind and pydantic
        # rejects a field the client never sent.
        if patch.get("kind") not in (None, stored.get("kind")):
            return {**patch, "conversion_goal_id": conversion_goal_id}

        merged = {**stored, **patch, "conversion_goal_id": conversion_goal_id}
        # No key on `schema_map` is required, so a top-level merge drops what the patch omits and the
        # query runner then skips the goal with a warning — a successful write that stops reporting.
        if isinstance(patch.get("schema_map"), dict) and isinstance(stored.get("schema_map"), dict):
            merged["schema_map"] = {**stored["schema_map"], **patch["schema_map"]}
        return merged

    def _index_of(self, goals: list[dict], conversion_goal_id: str) -> int:
        for index, goal in enumerate(goals):
            if isinstance(goal, dict) and goal.get("conversion_goal_id") == conversion_goal_id:
                return index
        raise NotFound(f"No conversion goal with id '{conversion_goal_id}'.")

    def _store_goals(self, config: TeamMarketingAnalyticsConfig, goals: list[dict], *, previous: list[dict]) -> None:
        # Direct, not through the `conversion_goals` setter: it would re-run the older validator on
        # every sibling goal and fail this write for a pre-existing row it never touched.
        config._conversion_goals = goals
        config.save()
        # Same trail the settings path produces, so an MCP-driven edit still records who did what.
        capture_team_config_diff(
            self.team,
            "marketing_analytics_config",
            {"conversion_goals": previous},
            {"conversion_goals": goals},
            context=self.get_serializer_context(),
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
        goal_id = request.validated_query_data["conversion_goal_id"]
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

    @validated_request(
        query_serializer=SetupPlanQuerySerializer,
        responses={
            200: OpenApiResponse(
                response=SetupPlanResponseSerializer,
                description="Ranked, machine-applicable setup suggestions plus per-capability readiness",
            ),
            404: OpenApiResponse(description="The marketing-analytics-setup feature flag is off for this team"),
        },
        summary="Get the marketing analytics setup plan",
        description=(
            "Rank everything wrong with a team's marketing analytics setup into concrete suggestions, each "
            "carrying the evidence behind it and — where one exists — an `apply` operation to pass straight "
            "to apply_setup_ops, plus a `readiness` block saying which capabilities (cost, ROAS, cost per "
            "customer, retention by channel) are unlocked and which suggestion is blocking each. Prefer this "
            "over `diagnose` when the question is 'what should I fix next': diagnose explains what is wrong, "
            "setup_plan says what to do about it in a form you can act on. Read-only."
        ),
    )
    @action(methods=["GET"], detail=False, url_path="setup_plan", required_scopes=["marketing_analytics:read"])
    def setup_plan(self, request: Request, *args, **kwargs) -> Response:
        # 404 rather than 403: an unreleased endpoint should look absent, not forbidden.
        if not _setup_enabled(request, self.team):
            raise NotFound("Marketing analytics setup is not enabled for this project.")

        date_from = request.validated_query_data["date_from"]
        # `IsAuthenticated` on the viewset rules out AnonymousUser, which is the only
        # reason `.pk` is optional here.
        user = cast(User, request.user)
        cache_key = _setup_plan_cache_key(self.team.pk, user.pk, date_from)
        if not request.validated_query_data["refresh"]:
            cached = cache.get(cache_key)
            if cached is not None:
                return Response(SetupPlanResponseSerializer(cached).data)
        try:
            plan = async_to_sync(get_setup_plan)(
                self.team,
                date_from=date_from,
                user=user,
            )
            # `model_dump(mode="json")` so the Pydantic op models inside each suggestion
            # come out as plain JSON — the serializer exposes them as JSONField.
            payload = plan.model_dump(mode="json")
            # Only a complete plan is worth reusing. A degraded one is missing whole
            # checks, and caching it would keep serving those gaps for a minute after
            # whatever caused them has recovered.
            if not plan.degraded:
                cache.set(cache_key, payload, _SETUP_PLAN_CACHE_SECONDS)
            return Response(SetupPlanResponseSerializer(payload).data)
        except Exception:
            logger.exception("marketing_setup_plan_failed", team_id=self.team.pk)
            return Response(
                {"detail": "Failed to build the setup plan. Check server logs for details."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @validated_request(
        request_serializer=ApplySetupOpsSerializer,
        responses={
            200: OpenApiResponse(
                response=ApplySetupOpsResponseSerializer,
                description="The applied operations and the ops that reverse them",
            ),
            400: OpenApiResponse(description="An operation was malformed, unsupported, or not applicable"),
            404: OpenApiResponse(description="The marketing-analytics-setup feature flag is off for this team"),
        },
        summary="Apply setup operations",
        description=(
            "Apply one or more setup operations from the setup plan, atomically. Either every operation "
            "lands or none does — a partially-applied batch has no well-defined undo. Returns `undo_ops`, "
            "computed from the pre-change state, which can be POSTed back to reverse the batch. Only send "
            "`apply` payloads returned by setup_plan."
        ),
    )
    @action(methods=["POST"], detail=False, url_path="apply_setup_ops", required_scopes=["marketing_analytics:write"])
    def apply_setup_ops(self, request: Request, *args, **kwargs) -> Response:
        # Same gate as setup_plan: the ops only come from a plan, so an unreleased
        # read side means there is nothing legitimate to apply.
        if not _setup_enabled(request, self.team):
            raise NotFound("Marketing analytics setup is not enabled for this project.")

        # Every op here writes a field the team PATCH puts in TEAM_CONFIG_ADMIN_FIELDS_SET,
        # and the goal ops write the same rows the sibling endpoints admin-gate. Without
        # this, `marketing_analytics:write` — which resolves to `editor`, what every
        # project member has — would be a way around both.
        self._require_project_admin()

        raw_ops = request.validated_data["ops"]
        try:
            ops = _SETUP_OPS_ADAPTER.validate_python(raw_ops)
        except PydanticValidationError as e:
            raise serializers.ValidationError({"ops": _readable_pydantic_errors(e)})

        for op in ops:
            if op.op in NAVIGATE_OPS:
                raise serializers.ValidationError(
                    {"ops": f"'{op.op}' is not applicable — it describes something the browser or a human does."}
                )
            if op.op in _UNIMPLEMENTED_OPS:
                raise serializers.ValidationError({"ops": f"'{op.op}' is not supported by this endpoint yet."})
            if op.op not in APPLICABLE_OPS:
                raise serializers.ValidationError({"ops": f"'{op.op}' is not a supported operation."})

        # One lock for the whole batch. The alternative — the frontend PATCHing the
        # whole config blob per suggestion — loses updates as soon as two apply
        # in sequence from one stale client snapshot, or a teammate edits in another tab.
        with transaction.atomic():
            config = self._locked_config()
            undo_ops: list[dict[str, Any]] = []
            for op in ops:
                # None means the op was already satisfied — re-adding an existing
                # mapping is a success, not a failure, so MCP retries are safe.
                inverse = _apply_setup_op(config, op)
                if inverse is not None:
                    undo_ops.append(inverse)
            config.save()

        # Reversed: undoing a batch means unwinding it from the last change back.
        undo_ops.reverse()

        # The config the plan was built from no longer exists, so any cached plan is
        # stale by definition. Without this, applying a change and reloading serves the
        # pre-change plan for up to a minute — the suggestion you just fixed still
        # sitting there, which reads as the apply having silently failed.
        _invalidate_setup_plan_cache(self.team.pk)

        # `_update_marketing_analytics_config` in posthog/api/team.py only diffs
        # sources_map / attribution_window_days / attribution_mode into the team
        # activity log, so mapping and goal changes made here would otherwise leave no
        # trace at all. This is the interim record; wiring `log_activity` properly is a
        # follow-up.
        logger.info(
            "marketing_setup_ops_applied",
            team_id=self.team.pk,
            user_id=request.user.pk,
            source=request.validated_data["source"],
            ops=[op.op for op in ops],
        )
        return Response(
            {
                "applied": [op.model_dump(mode="json") for op in ops],
                "undo_ops": undo_ops,
                "marketing_analytics_config": {
                    "sources_map": config.sources_map,
                    "conversion_goals": config.conversion_goals,
                    "custom_source_mappings": config.custom_source_mappings,
                    "campaign_name_mappings": config.campaign_name_mappings,
                    "campaign_field_preferences": config.campaign_field_preferences,
                },
            }
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
