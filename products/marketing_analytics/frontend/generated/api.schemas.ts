/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface ConversionGoalSummaryApi {
    /** Unique id of the goal (event name, action id, or DW goal id) */
    id: string
    /** Display name of the conversion goal */
    name: string
    /** Goal type — one of: EventsNode (PostHog event), ActionsNode (PostHog action), DataWarehouseNode (external table) */
    kind: string
    /** Human-readable target the goal matches (event/action name or table) */
    target_label: string
    /** Count of matching conversion events in the last 30 days */
    last_30d_count: number
    /**
     * Conversions whose utm_source matches a known integration. Null for DataWarehouseNode goals.
     * @nullable
     */
    integrated_count: number | null
    /**
     * Conversions with no utm_source at all (fix by tagging UTMs). Null for DataWarehouseNode goals.
     * @nullable
     */
    events_without_utm_source: number | null
    /**
     * Conversions with a utm_source that matches no integration (fix with custom_source_mappings). Null for DataWarehouseNode goals.
     * @nullable
     */
    events_with_unmatched_utm_source: number | null
    /**
     * Total non-integrated conversions (without + unmatched utm_source). Null for DataWarehouseNode goals.
     * @nullable
     */
    non_integrated_count: number | null
    /**
     * Percentage of conversions that are integrated. Null for DataWarehouseNode goals.
     * @nullable
     */
    integrated_pct: number | null
    /** Whether the goal could not be evaluated (e.g. deleted action) */
    is_misconfigured: boolean
    /**
     * Explanation when is_misconfigured is true
     * @nullable
     */
    misconfig_reason: string | null
    /** True when this 30d count may differ from the dashboard's attribution-windowed number */
    is_approximate: boolean
    /**
     * Explanation when is_approximate is true
     * @nullable
     */
    approximation_reason: string | null
}

export interface ConversionGoalsListResponseApi {
    /** One summary entry per configured conversion goal */
    goals: ConversionGoalSummaryApi[]
    /** The team's configured attribution window in days */
    attribution_window_days: number
    /** The team's attribution model (e.g. last_touch, first_touch, linear) */
    attribution_mode: string
    /** True if any goal is misconfigured */
    has_misconfigured: boolean
}

export interface RequiredTableStatusApi {
    /** Name of the required source table (e.g. 'campaign', 'campaign_stats') */
    table_name: string
    /** Whether the table exists as a schema on the connected source */
    present: boolean
    /** Whether the table is enabled for sync */
    should_sync: boolean
    /**
     * ExternalDataSchema status: Completed/Running/Failed/Paused/Cancelled, or null
     * @nullable
     */
    status: string | null
    /**
     * When this table last completed a sync
     * @nullable
     */
    last_synced_at: string | null
}

export interface DataSourceHealthEntryApi {
    /** External data source type key (e.g. 'GoogleAds', 'MetaAds') */
    source_type: string
    /** Whether this is a native marketing integration */
    is_native: boolean
    /** Human-readable integration name (e.g. 'Google Ads') */
    display_name: string
    /** Whether a live source of this type is connected */
    connected: boolean
    /**
     * When the source last completed a sync
     * @nullable
     */
    last_sync_at: string | null
    /** Sync status: ok/error/stale/tables_failed/not_connected/never */
    last_sync_status: string
    /**
     * Latest unresolved sync error message, if any
     * @nullable
     */
    last_error: string | null
    /** Rows synced in the last 24 hours */
    rows_last_24h: number
    /** Rows synced in the last 7 days */
    rows_last_7d: number
    /** Whether a column mapping exists for this source */
    sources_map_present: boolean
    /** Schema columns currently mapped for this source */
    schema_columns_mapped: string[]
    /** Required schema columns that are not yet mapped */
    schema_columns_required_missing: string[]
    /** Per-required-table sync status for this integration */
    required_tables: RequiredTableStatusApi[]
    /** URL to the Marketing analytics global settings page */
    settings_url: string
    /**
     * URL to the per-source Schemas tab, or null if not connected
     * @nullable
     */
    schemas_url: string | null
    /** Human-readable diagnosis of this source's health */
    diagnosis: string
    /**
     * Suggested fix when the source is unhealthy
     * @nullable
     */
    fix_suggestion: string | null
}

export interface DataSourceHealthResponseApi {
    /** One health entry per native integration */
    integrations: DataSourceHealthEntryApi[]
    /** True if any integration synced rows in the last 7 days */
    has_any_data: boolean
    /** Overall: healthy/degraded/broken/no_sources */
    overall_status: string
    /** Short human-readable summary of detected issues */
    issues_summary: string[]
}

export interface UnmatchedUtmSampleApi {
    /** A raw utm_source value that doesn't match the integration exactly */
    raw_value: string
    /** Number of events with this raw value in the window */
    event_count: number
    /**
     * Integration suggested by token match, if any
     * @nullable
     */
    suggested_integration: string | null
}

export interface AttributionHealthEntryApi {
    /** Integration key (e.g. 'google', 'meta') */
    integration_key: string
    /** Human-readable integration name */
    display_name: string
    /** Total events with any utm_source in the window */
    events_with_utm_last_7d: number
    /** Events whose utm_source matched this integration */
    events_matched_last_7d: number
    /** Events that look like this integration's but don't match exactly */
    events_unmatched_likely_yours_last_7d: number
    /**
     * Timestamp of the most recent matched event
     * @nullable
     */
    last_event_with_matching_utm_at: string | null
    /** Percentage of UTM events matched to this integration */
    matched_pct: number
    /** Sample of likely-yours unmatched utm_source values */
    sample_unmatched_utm_sources: UnmatchedUtmSampleApi[]
}

export interface RecommendedActionApi {
    /** Short title of the recommended action */
    title: string
    /** Detailed explanation of the action */
    detail: string
    /** Action severity */
    severity: string
    /**
     * Follow-up tool to call next, if any
     * @nullable
     */
    target_tool: string | null
}

export interface IntegrationDiagnosticApi {
    /** Integration key (e.g. 'google', 'meta') */
    integration_key: string
    /** External data source type key (e.g. 'GoogleAds') */
    source_type: string
    /** Human-readable integration name */
    display_name: string
    /** Per-integration status */
    overall_status: string
    /** Human-readable cross-domain diagnosis */
    diagnosis: string
    /** Data-source (sync) side health, or null if not connected */
    data_source?: DataSourceHealthEntryApi | null
    /** Attribution (UTM events) side health, or null if no data */
    attribution?: AttributionHealthEntryApi | null
    /** Recommended next steps for this integration */
    recommended_actions: RecommendedActionApi[]
}

export interface MarketingDiagnosticResponseApi {
    /** Per-integration cross-domain diagnostics */
    integrations: IntegrationDiagnosticApi[]
    /** healthy/degraded/broken/no_sources */
    overall_status: string
    /** One-line plain-English summary of the diagnostic */
    summary: string
    /** Conversion goal summary, when requested */
    conversion_goals?: ConversionGoalsListResponseApi | null
    /** Top global recommended actions across all integrations */
    recommended_actions: RecommendedActionApi[]
}

export interface GoalExplanationPeriodApi {
    /**
     * Start of the analyzed period (ISO)
     * @nullable
     */
    date_from: string | null
    /**
     * End of the analyzed period (ISO)
     * @nullable
     */
    date_to: string | null
}

export interface GoalEventSampleApi {
    /** UUID of the sampled conversion event */
    event_uuid: string
    /** When the event occurred */
    timestamp: string
    /** Distinct id associated with the event */
    distinct_id: string
    /**
     * utm_source value on the event, if any
     * @nullable
     */
    utm_source: string | null
    /**
     * utm_campaign value on the event, if any
     * @nullable
     */
    utm_campaign: string | null
    /**
     * Integration the utm_source matched, if any
     * @nullable
     */
    matched_integration: string | null
}

export interface GoalExplanationApi {
    /** Id of the explained conversion goal */
    goal_id: string
    /** Display name of the conversion goal */
    goal_name: string
    /** EventsNode/ActionsNode/DataWarehouseNode */
    kind: string
    /** The period the breakdown was computed over */
    period: GoalExplanationPeriodApi
    /** Total matching conversion events in the period */
    total_count: number
    /**
     * Events whose utm_source matched a known integration. Null for DataWarehouseNode.
     * @nullable
     */
    integrated_count: number | null
    /**
     * Events with no utm_source at all. Null for DataWarehouseNode.
     * @nullable
     */
    events_without_utm_source: number | null
    /**
     * Events with a utm_source matching no integration. Null for DataWarehouseNode.
     * @nullable
     */
    events_with_unmatched_utm_source: number | null
    /**
     * Total non-integrated events (without + unmatched). Null for DataWarehouseNode.
     * @nullable
     */
    non_integrated_count: number | null
    /**
     * List of [event_name, count] pairs
     * @items.minItems 2
     * @items.maxItems 2
     */
    by_event: [string, number][]
    /**
     * List of [utm_source, count] pairs
     * @items.minItems 2
     * @items.maxItems 2
     */
    by_utm_source: [string, number][]
    /**
     * List of [integration, count] pairs
     * @items.minItems 2
     * @items.maxItems 2
     */
    by_matched_integration: [string, number][]
    /** A small sample of matching events */
    samples: GoalEventSampleApi[]
    /** Caveats about the breakdown (sampling, attribution, etc.) */
    notes: string[]
}

export interface CandidateEventApi {
    /** Name of the candidate event */
    event_name: string
    /** Count of this event in the last 30 days */
    last_30d_count: number
    /** Distinct users who triggered the event in 30 days */
    distinct_users_30d: number
    /** Percentage of events that carry a utm_source */
    pct_with_utm_source: number
    /** Percentage of events that carry a utm_campaign */
    pct_with_utm_campaign: number
    /**
     * List of [utm_source, count] pairs
     * @items.minItems 2
     * @items.maxItems 2
     */
    top_utm_sources: [string, number][]
    /** Whether this event is already configured as a goal */
    is_already_a_goal: boolean
    /** Ranking score (higher is a stronger candidate) */
    suggestion_score: number
    /** Human-readable rationale for the suggestion */
    suggestion_reason: string
}

export interface EventSuggestionsResponseApi {
    /** Ranked candidate events for conversion goals */
    candidates: CandidateEventApi[]
    /** Lookback window in days used for the analysis */
    lookback_days: number
    /** Number of system/autocaptured events excluded */
    excluded_events_count: number
}

export interface SourceMappingSuggestionApi {
    /** The raw utm_source value seen on events */
    raw_utm_source: string
    /** Integration key it maps to */
    suggested_target: string
    /** Human-readable name of the suggested integration */
    suggested_target_display_name: string
    /** Why this mapping is suggested */
    reason: string
}

export interface CampaignMappingSuggestionApi {
    /** Integration key the campaign values belong to */
    integration: string
    /** Human-readable integration name */
    integration_display_name: string
    /** Proposed canonical campaign name */
    suggested_clean_name: string
    /** Raw campaign values clustered under this clean name */
    raw_campaign_values: string[]
    /** Confidence score for the clustering (0-1) */
    confidence: number
    /** Mapping method */
    method: string
    /** Why these campaign values were clustered together */
    reason: string
}

export interface RawUnmatchedSampleApi {
    /** A raw utm_source value matching no integration */
    raw_utm_source: string
    /** Number of events with this raw value in the window */
    event_count: number
    /**
     * Integration suggested by token match, if any
     * @nullable
     */
    suggested_integration: string | null
}

export interface CatalogueEntryApi {
    /** A raw utm_source value seen in the window */
    raw_utm_source: string
    /** Number of events with this value */
    event_count: number
    /**
     * Integration this value exactly matches, if any
     * @nullable
     */
    matched_integration: string | null
    /**
     * Human-readable name of the matched integration, if any
     * @nullable
     */
    matched_integration_display_name: string | null
    /**
     * Integration suggested by token match, if any
     * @nullable
     */
    suggested_integration: string | null
}

export interface CurrentMappingApi {
    /** A utm_source value already mapped to an integration */
    raw_utm_source: string
    /** Integration key it maps to */
    target: string
    /** Human-readable name of the target integration */
    target_display_name: string
    /** canonical or team_custom */
    source: string
}

export interface UtmMappingSuggestionsResponseApi {
    /** Suggested custom_source_mappings entries */
    source_suggestions: SourceMappingSuggestionApi[]
    /** Suggested campaign-name clusters (empty in v1) */
    campaign_suggestions: CampaignMappingSuggestionApi[]
    /** All unmatched raw utm_source values worth reviewing */
    raw_unmatched_samples: RawUnmatchedSampleApi[]
    /** Every utm_source value seen in the window, matched or not */
    full_utm_source_catalogue: CatalogueEntryApi[]
    /** Mappings already in effect (canonical + team_custom) */
    current_mappings: CurrentMappingApi[]
    /** Total events with an unmatched utm_source */
    total_unmatched_events_in_window: number
    /** Total events with any utm_source */
    total_events_with_utm_in_window: number
    /** Lookback window in days used for the analysis */
    lookback_days_used: number
    /** Caveats and guidance about the suggestions */
    notes: string[]
}

/**
 * * `error` - error
 * * `warning` - warning
 */
export type UtmIssueSeverityEnumApi = (typeof UtmIssueSeverityEnumApi)[keyof typeof UtmIssueSeverityEnumApi]

export const UtmIssueSeverityEnumApi = {
    Error: 'error',
    Warning: 'warning',
} as const

export interface UtmIssueApi {
    /** The UTM field with the issue (e.g. utm_campaign, utm_source) */
    field: string
    /** Issue severity level
     *
     * * `error` - error
     * * `warning` - warning */
    severity: UtmIssueSeverityEnumApi
    /** Human-readable description of the issue */
    message: string
}

export interface CampaignAuditResultApi {
    /** Campaign name from the ad platform */
    campaign_name: string
    /** Campaign ID from the ad platform */
    campaign_id: string
    /** Integration source name (e.g. google, meta) */
    source_name: string
    /** Total spend for this campaign in the period */
    spend: number
    /** Total clicks for this campaign */
    clicks: number
    /** Total impressions for this campaign */
    impressions: number
    /** Whether matching UTM pageview events were found */
    has_utm_events: boolean
    /** Number of matching UTM pageview events */
    event_count: number
    /** List of detected UTM configuration issues */
    issues: UtmIssueApi[]
}

/**
 * * `none` - none
 * * `auto` - auto
 * * `mapped` - mapped
 */
export type SourceMatchEnumApi = (typeof SourceMatchEnumApi)[keyof typeof SourceMatchEnumApi]

export const SourceMatchEnumApi = {
    None: 'none',
    Auto: 'auto',
    Mapped: 'mapped',
} as const

export interface UtmEventApi {
    /** UTM campaign value from pageview events */
    utm_campaign: string
    /** UTM source value from pageview events */
    utm_source: string
    /** Number of pageview events with this UTM combination */
    event_count: number
    /** How utm_campaign matched: none, auto (direct name/id), or mapped (manual mapping)
     *
     * * `none` - none
     * * `auto` - auto
     * * `mapped` - mapped */
    campaign_match: SourceMatchEnumApi
    /** How utm_source matched: none, auto (default source), or mapped (custom mapping)
     *
     * * `none` - none
     * * `auto` - auto
     * * `mapped` - mapped */
    source_match: SourceMatchEnumApi
    /**
     * Name of the matched campaign, if any
     * @nullable
     */
    matched_campaign: string | null
}

export interface UtmAuditResponseApi {
    /** Total number of campaigns with spend */
    total_campaigns: number
    /** Number of campaigns with UTM issues */
    campaigns_with_issues: number
    /** Number of campaigns without issues */
    campaigns_without_issues: number
    /** Total spend on campaigns with UTM issues */
    total_spend_at_risk: number
    /** Audit results per campaign */
    results: CampaignAuditResultApi[]
    /** All UTM events with match status */
    all_utm_events: UtmEventApi[]
}

export type MarketingAnalyticsDataSourcesRetrieveParams = {
    /**
     * Optional. Restrict to one integration (e.g. 'GoogleAds').
     * @nullable
     */
    source_type?: string | null
}

export type MarketingAnalyticsDiagnoseRetrieveParams = {
    /**
     * Lookback window for attribution health (1-365 days); defaults to 7
     * @minimum 1
     * @maximum 365
     */
    attribution_lookback_days?: number
    /**
     * Whether to include the conversion-goal summary in the diagnostic
     */
    include_conversion_goals?: boolean
    /**
     * Optional integration filter
     * @nullable
     */
    source_type?: string | null
}

export type MarketingAnalyticsExplainConversionGoalRetrieveParams = {
    /**
     * ISO start; defaults to 30 days ago
     * @nullable
     */
    date_from?: string | null
    /**
     * ISO end; defaults to now
     * @nullable
     */
    date_to?: string | null
    /**
     * Id of the conversion goal to explain (from list_conversion_goals).
     * @minLength 1
     */
    goal_id: string
}

export type MarketingAnalyticsSuggestConversionGoalsRetrieveParams = {
    /**
     * Minimum 30d event count to be a candidate
     */
    min_count?: number
    /**
     * Max candidates to return
     */
    top_n?: number
}

export type MarketingAnalyticsSuggestUtmMappingsRetrieveParams = {
    /**
     * Days of history to inspect (1-365); defaults to 90
     * @minimum 1
     * @maximum 365
     */
    lookback_days?: number
    /**
     * Only suggest for raw values with >= this many events
     */
    min_event_count?: number
}

export type MarketingAnalyticsUtmAuditRetrieveParams = {
    /**
     * Start date for the audit period
     * @minLength 1
     */
    date_from?: string
    /**
     * End date for the audit period
     * @nullable
     */
    date_to?: string | null
}
