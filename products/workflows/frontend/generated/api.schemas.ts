/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `team` - Only team
 * `organization` - Organization
 * `global` - Global
 */
export type HogFlowTemplateScopeEnumApi = (typeof HogFlowTemplateScopeEnumApi)[keyof typeof HogFlowTemplateScopeEnumApi]

export const HogFlowTemplateScopeEnumApi = {
    Team: 'team',
    Organization: 'organization',
    Global: 'global',
} as const

export interface HogFlowMaskingApi {
    /**
     * Hash TTL in seconds (60 to ~94M / 3y).
     * @minimum 60
     * @maximum 94608000
     * @nullable
     */
    ttl?: number | null
    /**
     * Min matching events before triggering (k-anonymity).
     * @nullable
     */
    threshold?: number | null
    /** HogQL template, e.g. '{person.properties.email}'. */
    hash: string
    /** Auto-compiled from hash. Do not set. */
    bytecode?: unknown
}

/**
 * * `exit_on_conversion` - Conversion
 * `exit_on_trigger_not_matched` - Trigger Not Matched
 * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
 * `exit_only_at_end` - Only At End
 */
export type ExitConditionEnumApi = (typeof ExitConditionEnumApi)[keyof typeof ExitConditionEnumApi]

export const ExitConditionEnumApi = {
    ExitOnConversion: 'exit_on_conversion',
    ExitOnTriggerNotMatched: 'exit_on_trigger_not_matched',
    ExitOnTriggerNotMatchedOrConversion: 'exit_on_trigger_not_matched_or_conversion',
    ExitOnlyAtEnd: 'exit_only_at_end',
} as const

/**
 * * `continue` - continue
 * `abort` - abort
 * `complete` - complete
 * `branch` - branch
 */
export type OnErrorEnumApi = (typeof OnErrorEnumApi)[keyof typeof OnErrorEnumApi]

export const OnErrorEnumApi = {
    Continue: 'continue',
    Abort: 'abort',
    Complete: 'complete',
    Branch: 'branch',
} as const

/**
 * * `events` - events
 * `person-updates` - person-updates
 * `data-warehouse-table` - data-warehouse-table
 */
export type HogFunctionFiltersSourceEnumApi =
    (typeof HogFunctionFiltersSourceEnumApi)[keyof typeof HogFunctionFiltersSourceEnumApi]

export const HogFunctionFiltersSourceEnumApi = {
    Events: 'events',
    PersonUpdates: 'person-updates',
    DataWarehouseTable: 'data-warehouse-table',
} as const

export type HogFunctionFiltersApiActionsItem = { [key: string]: unknown }

export type HogFunctionFiltersApiEventsItem = { [key: string]: unknown }

export type HogFunctionFiltersApiDataWarehouseItem = { [key: string]: unknown }

export type HogFunctionFiltersApiPropertiesItem = { [key: string]: unknown }

export interface HogFunctionFiltersApi {
    source?: HogFunctionFiltersSourceEnumApi
    actions?: HogFunctionFiltersApiActionsItem[]
    events?: HogFunctionFiltersApiEventsItem[]
    data_warehouse?: HogFunctionFiltersApiDataWarehouseItem[]
    properties?: HogFunctionFiltersApiPropertiesItem[]
    bytecode?: unknown
    transpiled?: unknown
    filter_test_accounts?: boolean
    bytecode_error?: string
}

/**
 * Custom action serializer for templates that skips input validation
(since templates should have default/empty values).
 */
export interface HogFlowTemplateActionApi {
    id: string
    /** @maxLength 400 */
    name: string
    description?: string
    on_error?: OnErrorEnumApi | null
    created_at?: number
    updated_at?: number
    filters?: HogFunctionFiltersApi | null
    /** @maxLength 100 */
    type: string
    config: unknown
    output_variable?: unknown
}

/**
 * @nullable
 */
export type HogFlowTemplateApiCreatedBy = { [key: string]: unknown } | null

/**
 * Variable: {key, type: string|number|boolean, default}.
 */
export type HogFlowTemplateApiVariablesItem = { [key: string]: string }

/**
 * Serializer for creating hog flow templates.
Validates and sanitizes the workflow before creating it as a template.
 */
export interface HogFlowTemplateApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    description?: string
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    tags?: string[]
    scope: HogFlowTemplateScopeEnumApi
    readonly created_at: string
    /** @nullable */
    readonly created_by: HogFlowTemplateApiCreatedBy
    readonly updated_at: string
    trigger?: unknown
    trigger_masking?: HogFlowMaskingApi | null
    conversion?: unknown
    exit_condition?: ExitConditionEnumApi
    edges?: unknown
    actions: HogFlowTemplateActionApi[]
    /**
     * @maxLength 400
     * @nullable
     */
    abort_action?: string | null
    variables?: HogFlowTemplateApiVariablesItem[]
}

export interface PaginatedHogFlowTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: HogFlowTemplateApi[]
}

/**
 * @nullable
 */
export type PatchedHogFlowTemplateApiCreatedBy = { [key: string]: unknown } | null

/**
 * Variable: {key, type: string|number|boolean, default}.
 */
export type PatchedHogFlowTemplateApiVariablesItem = { [key: string]: string }

/**
 * Serializer for creating hog flow templates.
Validates and sanitizes the workflow before creating it as a template.
 */
export interface PatchedHogFlowTemplateApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    description?: string
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    tags?: string[]
    scope?: HogFlowTemplateScopeEnumApi
    readonly created_at?: string
    /** @nullable */
    readonly created_by?: PatchedHogFlowTemplateApiCreatedBy
    readonly updated_at?: string
    trigger?: unknown
    trigger_masking?: HogFlowMaskingApi | null
    conversion?: unknown
    exit_condition?: ExitConditionEnumApi
    edges?: unknown
    actions?: HogFlowTemplateActionApi[]
    /**
     * @maxLength 400
     * @nullable
     */
    abort_action?: string | null
    variables?: PatchedHogFlowTemplateApiVariablesItem[]
}

/**
 * * `draft` - Draft
 * `active` - Active
 * `archived` - Archived
 */
export type HogFlowStatusEnumApi = (typeof HogFlowStatusEnumApi)[keyof typeof HogFlowStatusEnumApi]

export const HogFlowStatusEnumApi = {
    Draft: 'draft',
    Active: 'active',
    Archived: 'archived',
} as const

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface HogFlowMinimalApi {
    readonly id: string
    /** @nullable */
    readonly name: string | null
    readonly description: string
    readonly version: number
    readonly status: HogFlowStatusEnumApi
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    readonly trigger: unknown
    readonly trigger_masking: unknown
    readonly conversion: unknown
    readonly exit_condition: ExitConditionEnumApi
    readonly edges: unknown
    readonly actions: unknown
    /** @nullable */
    readonly abort_action: string | null
    readonly variables: unknown
    readonly billable_action_types: unknown
}

export interface PaginatedHogFlowMinimalListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: HogFlowMinimalApi[]
}

/**
 * Variable: {key, type: string|number|boolean, default}.
 */
export type HogFlowApiVariablesItem = { [key: string]: string }

/**
 * * `continue` - continue
 * `branch` - branch
 */
export type HogFlowEdgeTypeEnumApi = (typeof HogFlowEdgeTypeEnumApi)[keyof typeof HogFlowEdgeTypeEnumApi]

export const HogFlowEdgeTypeEnumApi = {
    Continue: 'continue',
    Branch: 'branch',
} as const

export interface HogFlowEdgeApi {
    /** Target action id. */
    to: string
    /** continue: fall-through (sequential or the no-match path of conditional_branch). branch: requires 'index' matching config.conditions[index].

  * `continue` - continue
  * `branch` - branch */
    type: HogFlowEdgeTypeEnumApi
    /** Required for type='branch'. Index into config.conditions on conditional_branch / wait_until_condition. */
    index?: number
    /** Source action id. */
    from: string
}

export interface HogFlowActionApi {
    /** Unique node ID within the workflow. */
    id: string
    /**
     * Display name.
     * @maxLength 400
     */
    name: string
    /** Optional description. */
    description?: string
    /** On failure: continue (skip), abort (stop), complete (mark done), branch (follow error edge).

  * `continue` - continue
  * `abort` - abort
  * `complete` - complete
  * `branch` - branch */
    on_error?: OnErrorEnumApi | null
    /** Created at (epoch ms). Frontend-managed. */
    created_at?: number
    /** Updated at (epoch ms). Frontend-managed. */
    updated_at?: number
    /** Property filters gating this action. */
    filters?: HogFunctionFiltersApi | null
    /**
     * trigger | function | function_email | function_sms | function_push | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.
     * @maxLength 100
     */
    type: string
    /** Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, max_wait_duration: <duration>} (same rules as delay). exit: {reason}. */
    config: unknown
    /** Output variable definition for downstream actions. */
    output_variable?: unknown
}

/**
 * * `active` - Active
 * `paused` - Paused
 * `completed` - Completed
 */
export type HogFlowScheduleStatusEnumApi =
    (typeof HogFlowScheduleStatusEnumApi)[keyof typeof HogFlowScheduleStatusEnumApi]

export const HogFlowScheduleStatusEnumApi = {
    Active: 'active',
    Paused: 'paused',
    Completed: 'completed',
} as const

export interface HogFlowScheduleApi {
    readonly id: string
    /** iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour. */
    rrule: string
    /** ISO 8601 datetime the schedule starts from. */
    starts_at: string
    /**
     * IANA timezone for interpreting the RRULE (default 'UTC').
     * @maxLength 64
     */
    timezone?: string
    /** Variable value overrides merged with the workflow defaults on each run. */
    variables?: unknown
    /** active, paused, or completed (set once the RRULE's COUNT/UNTIL is exhausted).

  * `active` - Active
  * `paused` - Paused
  * `completed` - Completed */
    readonly status: HogFlowScheduleStatusEnumApi
    /**
     * Next scheduled fire time, computed by the scheduler.
     * @nullable
     */
    readonly next_run_at: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface HogFlowApi {
    readonly id: string
    /**
     * Workflow name.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional description. */
    description?: string
    readonly version: number
    /** draft (no execution), active (live), archived (disabled).

  * `draft` - Draft
  * `active` - Active
  * `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    readonly trigger: unknown
    /** Optional dedup: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Server compiles bytecode from hash. Omit to disable. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side. */
    conversion?: unknown
    /** exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').

  * `exit_on_conversion` - Conversion
  * `exit_on_trigger_not_matched` - Trigger Not Matched
  * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
  * `exit_only_at_end` - Only At End */
    exit_condition?: ExitConditionEnumApi
    /** Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch / wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise). */
    edges?: HogFlowEdgeApi[]
    /** Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too. */
    actions: HogFlowActionApi[]
    /** @nullable */
    readonly abort_action: string | null
    /** Workflow vars (key, type, default). Total <5KB. */
    variables?: HogFlowApiVariablesItem[]
    readonly billable_action_types: unknown
    /** Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). A batch/schedule workflow only fires when it's active AND has an active schedule. Empty for non-scheduled workflows. */
    readonly schedules: readonly HogFlowScheduleApi[]
}

/**
 * Variable: {key, type: string|number|boolean, default}.
 */
export type PatchedHogFlowApiVariablesItem = { [key: string]: string }

export interface PatchedHogFlowApi {
    readonly id?: string
    /**
     * Workflow name.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional description. */
    description?: string
    readonly version?: number
    /** draft (no execution), active (live), archived (disabled).

  * `draft` - Draft
  * `active` - Active
  * `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    readonly trigger?: unknown
    /** Optional dedup: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Server compiles bytecode from hash. Omit to disable. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal: {filters: [<cond>, ...], window_minutes}. <cond>: {key, value, operator, type: event|person|group}. Empty filters = any event in window. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side. */
    conversion?: unknown
    /** exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').

  * `exit_on_conversion` - Conversion
  * `exit_on_trigger_not_matched` - Trigger Not Matched
  * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
  * `exit_only_at_end` - Only At End */
    exit_condition?: ExitConditionEnumApi
    /** Graph edges: [{from, to, type: 'continue'|'branch', index?}]. 'continue' = fall-through (sequential, or no-match path of conditional_branch). 'branch' requires 'index': matches config.conditions[index] on conditional_branch / wait_until_condition. Every non-exit action needs a reachable next action ('No next action found' otherwise). */
    edges?: HogFlowEdgeApi[]
    /** Ordered action nodes. Exactly one type='trigger' required. Typically one type='exit' too. */
    actions?: HogFlowActionApi[]
    /** @nullable */
    readonly abort_action?: string | null
    /** Workflow vars (key, type, default). Total <5KB. */
    variables?: PatchedHogFlowApiVariablesItem[]
    readonly billable_action_types?: unknown
    /** Recurring schedules attached to this workflow (read-only here; manage via the schedules sub-resource). A batch/schedule workflow only fires when it's active AND has an active schedule. Empty for non-scheduled workflows. */
    readonly schedules?: readonly HogFlowScheduleApi[]
}

/**
 * * `waiting` - Waiting
 * `queued` - Queued
 * `active` - Active
 * `completed` - Completed
 * `cancelled` - Cancelled
 * `failed` - Failed
 */
export type HogFlowBatchJobStatusEnumApi =
    (typeof HogFlowBatchJobStatusEnumApi)[keyof typeof HogFlowBatchJobStatusEnumApi]

export const HogFlowBatchJobStatusEnumApi = {
    Waiting: 'waiting',
    Queued: 'queued',
    Active: 'active',
    Completed: 'completed',
    Cancelled: 'cancelled',
    Failed: 'failed',
} as const

export interface HogFlowBatchJobApi {
    readonly id: string
    /** Not currently tracked — stays at its initial value. Use the workflow logs/metrics endpoints for run outcome.

  * `waiting` - Waiting
  * `queued` - Queued
  * `active` - Active
  * `completed` - Completed
  * `cancelled` - Cancelled
  * `failed` - Failed */
    status?: HogFlowBatchJobStatusEnumApi
    /** ID of the workflow this batch run belongs to. */
    hog_flow: string
    /** Audience snapshot the run fanned out to, taken from the workflow's batch trigger filters. */
    filters?: unknown
    /** Variable value overrides applied to this run. */
    variables?: unknown
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
}

/**
 * Test trigger payload, typically {event, person, groups}.
 */
export type HogFlowInvocationApiGlobals = { [key: string]: unknown }

export interface HogFlowInvocationApi {
    /** Optional override; omit to use saved definition. */
    configuration?: HogFlowApi
    /** Test trigger payload, typically {event, person, groups}. */
    globals?: HogFlowInvocationApiGlobals
    /** True (default) mocks HTTP/email/SMS. False fires real side effects. */
    mock_async_functions?: boolean
    /** Start from this action ID instead of the trigger. */
    current_action_id?: string
}

export interface AppMetricSeriesApi {
    name: string
    values: number[]
}

export interface AppMetricsResponseApi {
    labels: string[]
    series: AppMetricSeriesApi[]
}

export type AppMetricsTotalsResponseApiTotals = { [key: string]: number }

export interface AppMetricsTotalsResponseApi {
    totals: AppMetricsTotalsResponseApiTotals
}

export interface PatchedHogFlowScheduleApi {
    readonly id?: string
    /** iCalendar RRULE string (e.g. 'FREQ=DAILY;INTERVAL=1'). Must produce occurrences at most once per hour. */
    rrule?: string
    /** ISO 8601 datetime the schedule starts from. */
    starts_at?: string
    /**
     * IANA timezone for interpreting the RRULE (default 'UTC').
     * @maxLength 64
     */
    timezone?: string
    /** Variable value overrides merged with the workflow defaults on each run. */
    variables?: unknown
    /** active, paused, or completed (set once the RRULE's COUNT/UNTIL is exhausted).

  * `active` - Active
  * `paused` - Paused
  * `completed` - Completed */
    readonly status?: HogFlowScheduleStatusEnumApi
    /**
     * Next scheduled fire time, computed by the scheduler.
     * @nullable
     */
    readonly next_run_at?: string | null
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Property filters to apply
 */
export type BlastRadiusRequestApiFilters = { [key: string]: unknown }

export interface BlastRadiusRequestApi {
    /** Property filters to apply */
    filters: BlastRadiusRequestApiFilters
    /**
     * Group type index for group-based targeting
     * @nullable
     */
    group_type_index?: number | null
}

export interface BlastRadiusApi {
    /** Number of users matching the filters */
    affected: number
    /** Total number of users */
    total: number
}

export type HogFlowTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type HogFlowTemplatesLogsRetrieveParams = {
    /**
     * Only return entries after this ISO 8601 timestamp.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}

export type HogFlowsListParams = {
    created_at?: string
    created_by?: number
    id?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * * `draft` - Draft
     * `active` - Active
     * `archived` - Archived
     */
    status?: HogFlowsListStatus
    updated_at?: string
}

export type HogFlowsListStatus = (typeof HogFlowsListStatus)[keyof typeof HogFlowsListStatus]

export const HogFlowsListStatus = {
    Active: 'active',
    Archived: 'archived',
    Draft: 'draft',
} as const

export type HogFlowsLogsRetrieveParams = {
    /**
     * Only return entries after this ISO 8601 timestamp.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}

export type HogFlowsMetricsRetrieveParams = {
    /**
     * Start of the time range. Accepts relative formats like '-7d', '-24h' or ISO 8601 timestamps. Defaults to '-7d'.
     * @minLength 1
     */
    after?: string
    /**
     * End of the time range. Same format as 'after'. Defaults to now.
     * @minLength 1
     */
    before?: string
    /**
 * Group the series by metric 'name' or 'kind'. Defaults to 'kind'.

* `name` - name
* `kind` - kind
 * @minLength 1
 */
    breakdown_by?: HogFlowsMetricsRetrieveBreakdownBy
    /**
     * Filter metrics to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
 * Time bucket size for the series. One of: hour, day, week. Defaults to 'day'.

* `hour` - hour
* `day` - day
* `week` - week
 * @minLength 1
 */
    interval?: HogFlowsMetricsRetrieveInterval
    /**
     * Comma-separated metric kinds to filter by, e.g. 'success,failure'.
     * @minLength 1
     */
    kind?: string
    /**
     * Comma-separated metric names to filter by.
     * @minLength 1
     */
    name?: string
}

export type HogFlowsMetricsRetrieveBreakdownBy =
    (typeof HogFlowsMetricsRetrieveBreakdownBy)[keyof typeof HogFlowsMetricsRetrieveBreakdownBy]

export const HogFlowsMetricsRetrieveBreakdownBy = {
    Name: 'name',
    Kind: 'kind',
} as const

export type HogFlowsMetricsRetrieveInterval =
    (typeof HogFlowsMetricsRetrieveInterval)[keyof typeof HogFlowsMetricsRetrieveInterval]

export const HogFlowsMetricsRetrieveInterval = {
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
} as const

export type HogFlowsMetricsTotalsRetrieveParams = {
    /**
     * Start of the time range. Accepts relative formats like '-7d', '-24h' or ISO 8601 timestamps. Defaults to '-7d'.
     * @minLength 1
     */
    after?: string
    /**
     * End of the time range. Same format as 'after'. Defaults to now.
     * @minLength 1
     */
    before?: string
    /**
 * Group the series by metric 'name' or 'kind'. Defaults to 'kind'.

* `name` - name
* `kind` - kind
 * @minLength 1
 */
    breakdown_by?: HogFlowsMetricsTotalsRetrieveBreakdownBy
    /**
     * Filter metrics to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
 * Time bucket size for the series. One of: hour, day, week. Defaults to 'day'.

* `hour` - hour
* `day` - day
* `week` - week
 * @minLength 1
 */
    interval?: HogFlowsMetricsTotalsRetrieveInterval
    /**
     * Comma-separated metric kinds to filter by, e.g. 'success,failure'.
     * @minLength 1
     */
    kind?: string
    /**
     * Comma-separated metric names to filter by.
     * @minLength 1
     */
    name?: string
}

export type HogFlowsMetricsTotalsRetrieveBreakdownBy =
    (typeof HogFlowsMetricsTotalsRetrieveBreakdownBy)[keyof typeof HogFlowsMetricsTotalsRetrieveBreakdownBy]

export const HogFlowsMetricsTotalsRetrieveBreakdownBy = {
    Name: 'name',
    Kind: 'kind',
} as const

export type HogFlowsMetricsTotalsRetrieveInterval =
    (typeof HogFlowsMetricsTotalsRetrieveInterval)[keyof typeof HogFlowsMetricsTotalsRetrieveInterval]

export const HogFlowsMetricsTotalsRetrieveInterval = {
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
} as const
