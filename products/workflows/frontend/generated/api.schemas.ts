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
     * Time-to-live in seconds for the masking hash. Min 60s, max 3 years.
     * @minimum 60
     * @maximum 94608000
     * @nullable
     */
    ttl?: number | null
    /**
     * Minimum number of matching events before the workflow triggers (k-anonymity threshold).
     * @nullable
     */
    threshold?: number | null
    /** HogQL template expression used as the masking key (e.g. '{person.properties.email}'). */
    hash: string
    /** Compiled bytecode for the hash template. Auto-generated server-side from the hash expression. */
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
 * Variable definition. Keys: 'key' (unique identifier used in templating), 'type' (string|number|boolean), 'default' (initial value as a string).
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
 * Variable definition. Keys: 'key' (unique identifier used in templating), 'type' (string|number|boolean), 'default' (initial value as a string).
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
 * Variable definition. Keys: 'key' (unique identifier used in templating), 'type' (string|number|boolean), 'default' (initial value as a string).
 */
export type HogFlowApiVariablesItem = { [key: string]: string }

export interface HogFlowActionApi {
    /** Unique identifier for this action node within the workflow graph. */
    id: string
    /**
     * Human-readable name for the action node.
     * @maxLength 400
     */
    name: string
    /** Optional description of what this action does. */
    description?: string
    /** Behavior when this action fails: continue (skip and proceed), abort (stop workflow), complete (mark as done), or branch (follow error edge).

  * `continue` - continue
  * `abort` - abort
  * `complete` - complete
  * `branch` - branch */
    on_error?: OnErrorEnumApi | null
    /** Unix epoch milliseconds when the action was added. Auto-managed by the frontend. */
    created_at?: number
    /** Unix epoch milliseconds when the action was last modified. Auto-managed by the frontend. */
    updated_at?: number
    /** Property filters that gate execution of this action. */
    filters?: HogFunctionFiltersApi | null
    /**
     * Action type. One of: trigger, function, function_email, function_sms, function_push, delay, conditional_branch, wait_until_condition, wait_until_time_window, random_cohort_branch, exit.
     * @maxLength 100
     */
    type: string
    /** Type-specific configuration. For triggers: {type: 'event'|'webhook'|'manual'|'batch'|'schedule'|'tracking_pixel', filters?}. filters is an object: {events: [{id, name, type: 'events', properties: [<property condition>]}], properties: [<property condition>], actions: [...], filter_test_accounts: <bool>}. Each property condition is {key, value, operator, type: 'event'|'person'|'group'}. Example: {"type": "event", "filters": {"events": [{"id": "$pageview", "name": "$pageview", "type": "events", "properties": [{"key": "$current_url", "value": "/pricing", "operator": "icontains", "type": "event"}]}]}}. For function*: {template_id, inputs}. For delay: {delay_duration: <string>} — duration format is '<number><unit>' where unit is one of m|h|d (minutes, hours, days), e.g. '30m', '1.5h', '2d'. Fractions allowed — for sub-minute delays use a fraction of a minute (e.g. '0.5m' = 30 seconds); seconds are not supported. Per-unit max enforced by executor: m<=60, h<=24, d<=30; values above these are SILENTLY CLAMPED — to wait >24h use days, etc. Max effective duration is 30d. For conditional_branch: {conditions: [{filters: {...}}, ...]} — each condition's array position determines which 'branch' edge fires when it matches (condition at index 0 -> edge with index:0). For wait_until_condition: {condition: {filters: {...}}, max_wait_duration: <duration string>} — same duration format and clamping rules as delay. For exit: {reason: <string>}. */
    config: unknown
    /** Variable definition to store this action's output for use by downstream actions. */
    output_variable?: unknown
}

export interface HogFlowApi {
    readonly id: string
    /**
     * Human-readable name for the workflow.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional description of the workflow's purpose. */
    description?: string
    readonly version: number
    /** Workflow state: draft (editing, no live execution), active (processing events live), or archived (soft-deleted, no execution).

  * `draft` - Draft
  * `active` - Active
  * `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    readonly trigger: unknown
    /** Optional deduplication config that prevents the same entity from entering the workflow multiple times within a TTL window. Shape: {hash: <HogQL template, e.g. '{person.properties.email}'>, ttl: <seconds, 60-94608000>, threshold?: <int, min matches before triggering>}. The server compiles 'bytecode' from 'hash' automatically — do not set bytecode yourself. Omit entirely to disable deduplication. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal. Shape: {filters: [<property condition>, ...], window_minutes: <int>}. 'filters' is an array of property conditions; each condition is {key, value, operator, type} where type is 'event' | 'person' | 'group'. Example: {"filters": [{"key": "plan", "value": "paid", "operator": "exact", "type": "person"}], "window_minutes": 60}. Empty array means any event in the window counts. Required when exit_condition is exit_on_conversion or exit_on_trigger_not_matched_or_conversion. 'bytecode' is compiled server-side from 'filters' — do not set it. */
    conversion?: unknown
    /** When a person exits the workflow. exit_only_at_end (default): only exits at an explicit exit node. exit_on_conversion: also exits early if a conversion event fires anywhere mid-workflow — REQUIRES 'conversion' to be set, otherwise this is a silent no-op. exit_on_trigger_not_matched: exits early if the trigger filter stops matching for that person. exit_on_trigger_not_matched_or_conversion: both of the above — also requires 'conversion' to be set.

  * `exit_on_conversion` - Conversion
  * `exit_on_trigger_not_matched` - Trigger Not Matched
  * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
  * `exit_only_at_end` - Only At End */
    exit_condition?: ExitConditionEnumApi | null
    /** Graph edges connecting action nodes. Array of {from, to, type, index?} objects. type='continue' is the default/fall-through edge — followed when an action does not select a specific branch (sequential nodes, the no-match path of a conditional_branch). type='branch' requires an integer 'index' field — followed when a conditional_branch / wait_until_condition action matches the condition at that index in its config.conditions array. Example for a conditional_branch with one condition: {from: 'cond', to: 'matched_node', type: 'branch', index: 0} for the matched path AND {from: 'cond', to: 'else_node', type: 'continue'} for the no-match path. Every non-exit action needs a reachable next action — orphan paths cause the runtime to error with 'No next action found'. */
    edges?: unknown
    /** Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'. Typically also includes one action with type='exit'. */
    actions: HogFlowActionApi[]
    /** @nullable */
    readonly abort_action: string | null
    /** Workflow-level variables that persist across actions. Each variable has key, type, and default. Total serialized size must be under 5KB. */
    variables?: HogFlowApiVariablesItem[]
    readonly billable_action_types: unknown
}

/**
 * Variable definition. Keys: 'key' (unique identifier used in templating), 'type' (string|number|boolean), 'default' (initial value as a string).
 */
export type PatchedHogFlowApiVariablesItem = { [key: string]: string }

export interface PatchedHogFlowApi {
    readonly id?: string
    /**
     * Human-readable name for the workflow.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional description of the workflow's purpose. */
    description?: string
    readonly version?: number
    /** Workflow state: draft (editing, no live execution), active (processing events live), or archived (soft-deleted, no execution).

  * `draft` - Draft
  * `active` - Active
  * `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    readonly trigger?: unknown
    /** Optional deduplication config that prevents the same entity from entering the workflow multiple times within a TTL window. Shape: {hash: <HogQL template, e.g. '{person.properties.email}'>, ttl: <seconds, 60-94608000>, threshold?: <int, min matches before triggering>}. The server compiles 'bytecode' from 'hash' automatically — do not set bytecode yourself. Omit entirely to disable deduplication. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal. Shape: {filters: [<property condition>, ...], window_minutes: <int>}. 'filters' is an array of property conditions; each condition is {key, value, operator, type} where type is 'event' | 'person' | 'group'. Example: {"filters": [{"key": "plan", "value": "paid", "operator": "exact", "type": "person"}], "window_minutes": 60}. Empty array means any event in the window counts. Required when exit_condition is exit_on_conversion or exit_on_trigger_not_matched_or_conversion. 'bytecode' is compiled server-side from 'filters' — do not set it. */
    conversion?: unknown
    /** When a person exits the workflow. exit_only_at_end (default): only exits at an explicit exit node. exit_on_conversion: also exits early if a conversion event fires anywhere mid-workflow — REQUIRES 'conversion' to be set, otherwise this is a silent no-op. exit_on_trigger_not_matched: exits early if the trigger filter stops matching for that person. exit_on_trigger_not_matched_or_conversion: both of the above — also requires 'conversion' to be set.

  * `exit_on_conversion` - Conversion
  * `exit_on_trigger_not_matched` - Trigger Not Matched
  * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
  * `exit_only_at_end` - Only At End */
    exit_condition?: ExitConditionEnumApi | null
    /** Graph edges connecting action nodes. Array of {from, to, type, index?} objects. type='continue' is the default/fall-through edge — followed when an action does not select a specific branch (sequential nodes, the no-match path of a conditional_branch). type='branch' requires an integer 'index' field — followed when a conditional_branch / wait_until_condition action matches the condition at that index in its config.conditions array. Example for a conditional_branch with one condition: {from: 'cond', to: 'matched_node', type: 'branch', index: 0} for the matched path AND {from: 'cond', to: 'else_node', type: 'continue'} for the no-match path. Every non-exit action needs a reachable next action — orphan paths cause the runtime to error with 'No next action found'. */
    edges?: unknown
    /** Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'. Typically also includes one action with type='exit'. */
    actions?: HogFlowActionApi[]
    /** @nullable */
    readonly abort_action?: string | null
    /** Workflow-level variables that persist across actions. Each variable has key, type, and default. Total serialized size must be under 5KB. */
    variables?: PatchedHogFlowApiVariablesItem[]
    readonly billable_action_types?: unknown
}

/**
 * Test event data to trigger the workflow with. Object shape matches the trigger payload — typically {event: {...}, person: {...}, groups: {...}}.
 */
export type HogFlowInvocationApiGlobals = { [key: string]: unknown }

export interface HogFlowInvocationApi {
    /** Optional workflow configuration override for the test run. If omitted, uses the saved workflow definition. Pass this only to test an unsaved edit. */
    configuration?: HogFlowApi
    /** Test event data to trigger the workflow with. Object shape matches the trigger payload — typically {event: {...}, person: {...}, groups: {...}}. */
    globals?: HogFlowInvocationApiGlobals
    /** When true (default), async actions (HTTP requests, emails, SMS) are simulated rather than executed. Set false to actually fire side effects — use with caution. */
    mock_async_functions?: boolean
    /** Start execution from a specific action node ID instead of the trigger. Useful for testing mid-workflow actions. */
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
    rrule: string
    starts_at: string
    /** @maxLength 64 */
    timezone?: string
    variables?: unknown
    readonly status: HogFlowScheduleStatusEnumApi
    /** @nullable */
    readonly next_run_at: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedHogFlowScheduleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: HogFlowScheduleApi[]
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

export type HogFlowsSchedulesListParams = {
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
    status?: HogFlowsSchedulesListStatus
    updated_at?: string
}

export type HogFlowsSchedulesListStatus = (typeof HogFlowsSchedulesListStatus)[keyof typeof HogFlowsSchedulesListStatus]

export const HogFlowsSchedulesListStatus = {
    Active: 'active',
    Archived: 'archived',
    Draft: 'draft',
} as const

export type HogFlowsSchedulesCreateParams = {
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
    status?: HogFlowsSchedulesCreateStatus
    updated_at?: string
}

export type HogFlowsSchedulesCreateStatus =
    (typeof HogFlowsSchedulesCreateStatus)[keyof typeof HogFlowsSchedulesCreateStatus]

export const HogFlowsSchedulesCreateStatus = {
    Active: 'active',
    Archived: 'archived',
    Draft: 'draft',
} as const
