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
    /** Compiled bytecode for the hash template. Auto-generated server-side. */
    bytecode?: unknown | null
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

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
    bytecode?: unknown | null
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
    on_error?: OnErrorEnumApi | NullEnumApi | null
    created_at?: number
    updated_at?: number
    filters?: HogFunctionFiltersApi | null
    /** @maxLength 100 */
    type: string
    config: unknown
    output_variable?: unknown | null
}

/**
 * @nullable
 */
export type HogFlowTemplateApiCreatedBy = { [key: string]: unknown } | null | null

/**
 * Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value).
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
    conversion?: unknown | null
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
export type PatchedHogFlowTemplateApiCreatedBy = { [key: string]: unknown } | null | null

/**
 * Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value).
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
    conversion?: unknown | null
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
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
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
    readonly trigger_masking: unknown | null
    readonly conversion: unknown | null
    readonly exit_condition: ExitConditionEnumApi
    readonly edges: unknown
    readonly actions: unknown
    /** @nullable */
    readonly abort_action: string | null
    readonly variables: unknown | null
    readonly billable_action_types: unknown | null
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
 * Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value).
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
    on_error?: OnErrorEnumApi | NullEnumApi | null
    /** Unix epoch milliseconds when the action was added. Auto-managed by the frontend. */
    created_at?: number
    /** Unix epoch milliseconds when the action was last modified. Auto-managed by the frontend. */
    updated_at?: number
    /** Property filters that gate execution of this action. */
    filters?: HogFunctionFiltersApi | null
    /**
     * Action type: trigger, function, function_email, function_sms, function_push, delay, conditional_branch, wait_until_condition, random_cohort_branch, exit.
     * @maxLength 100
     */
    type: string
    /** Type-specific configuration. For triggers: {type, filters}. For functions: {template_id, inputs}. For delays: {delay_duration, e.g. '30m', '2h', '1d'}. For conditional branches: {conditions}. */
    config: unknown
    /** Variable definition to store this action's output for use by downstream actions. */
    output_variable?: unknown | null
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
    /** Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).

* `draft` - Draft
* `active` - Active
* `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    readonly trigger: unknown
    /** Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition. */
    conversion?: unknown | null
    /** When a person exits the workflow: exit_on_conversion, exit_on_trigger_not_matched, exit_on_trigger_not_matched_or_conversion, or exit_only_at_end.

* `exit_on_conversion` - Conversion
* `exit_on_trigger_not_matched` - Trigger Not Matched
* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
* `exit_only_at_end` - Only At End */
    exit_condition?: ExitConditionEnumApi | NullEnumApi | null
    /** Graph edges connecting action nodes. Array of {source, target} objects defining the execution flow between actions. */
    edges?: unknown
    /** Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'. */
    actions: HogFlowActionApi[]
    /** @nullable */
    readonly abort_action: string | null
    /** Workflow-level variables that persist across actions. Each variable has a key, type, and default value. Total size must be under 5KB. */
    variables?: HogFlowApiVariablesItem[]
    readonly billable_action_types: unknown | null
}

/**
 * Variable definition with keys: 'key' (unique identifier), 'type' (string/number/boolean), 'default' (initial value).
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
    /** Workflow state: draft (editing), active (live and processing events), or archived (soft-deleted).

* `draft` - Draft
* `active` - Active
* `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    readonly trigger?: unknown
    /** Optional masking/deduplication configuration. Prevents the same entity from entering the workflow multiple times within a TTL window. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal definition with filters and bytecode. Used with exit_on_conversion exit condition. */
    conversion?: unknown | null
    /** When a person exits the workflow: exit_on_conversion, exit_on_trigger_not_matched, exit_on_trigger_not_matched_or_conversion, or exit_only_at_end.

* `exit_on_conversion` - Conversion
* `exit_on_trigger_not_matched` - Trigger Not Matched
* `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
* `exit_only_at_end` - Only At End */
    exit_condition?: ExitConditionEnumApi | NullEnumApi | null
    /** Graph edges connecting action nodes. Array of {source, target} objects defining the execution flow between actions. */
    edges?: unknown
    /** Ordered list of action nodes in the workflow. Must include exactly one action with type='trigger'. */
    actions?: HogFlowActionApi[]
    /** @nullable */
    readonly abort_action?: string | null
    /** Workflow-level variables that persist across actions. Each variable has a key, type, and default value. Total size must be under 5KB. */
    variables?: PatchedHogFlowApiVariablesItem[]
    readonly billable_action_types?: unknown | null
}

/**
 * Test event data to trigger the workflow with. Object with keys like 'event', 'person', 'groups' matching the event shape.
 */
export type HogFlowInvocationApiGlobals = { [key: string]: unknown }

export interface HogFlowInvocationApi {
    /** Optional workflow configuration override for the test run. If omitted, uses the saved workflow definition. */
    configuration?: HogFlowApi
    /** Test event data to trigger the workflow with. Object with keys like 'event', 'person', 'groups' matching the event shape. */
    globals?: HogFlowInvocationApiGlobals
    /** When true (default), async actions (HTTP requests, emails) are simulated rather than executed for safety. */
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
    updated_at?: string
}

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
    updated_at?: string
}

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
    updated_at?: string
}
