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
 * * `organization` - Organization
 * * `global` - Global
 */
export type HogFlowTemplateScopeEnumApi = (typeof HogFlowTemplateScopeEnumApi)[keyof typeof HogFlowTemplateScopeEnumApi]

export const HogFlowTemplateScopeEnumApi = {
    Team: 'team',
    Organization: 'organization',
    Global: 'global',
} as const

export interface HogFlowMaskingApi {
    /**
     * Seconds (60 to ~94M / 3y) to suppress repeat firings of the same hash.
     * @minimum 60
     * @maximum 94608000
     * @nullable
     */
    ttl?: number | null
    /**
     * Fire once per N matches of the same hash within ttl — a sampler: N=3 fires on the 1st, 4th, 7th… match. Omit to fire on the first match, then suppress repeats within ttl.
     * @nullable
     */
    threshold?: number | null
    /** HogQL template defining the dedup/grouping key, e.g. '{person.id}' (once per person) within ttl. */
    hash: string
    /** Auto-compiled from hash. Do not set. */
    bytecode?: unknown
}

/**
 * * `exit_on_conversion` - Conversion
 * * `exit_on_trigger_not_matched` - Trigger Not Matched
 * * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
 * * `exit_only_at_end` - Only At End
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
 * * `abort` - abort
 */
export type OnErrorEnumApi = (typeof OnErrorEnumApi)[keyof typeof OnErrorEnumApi]

export const OnErrorEnumApi = {
    Continue: 'continue',
    Abort: 'abort',
} as const

/**
 * * `events` - events
 * * `person-updates` - person-updates
 * * `data-warehouse-table` - data-warehouse-table
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
 * (since templates should have default/empty values).
 */
export interface HogFlowTemplateActionApi {
    id: string
    /** @maxLength 400 */
    name: string
    description?: string
    /** On failure: continue (skip the action and proceed) or abort (stop the run).
     *
     * * `continue` - continue
     * * `abort` - abort */
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
 * Validates and sanitizes the workflow before creating it as a template.
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
 * Validates and sanitizes the workflow before creating it as a template.
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
 * * `active` - Active
 * * `archived` - Archived
 */
export type HogFlowStatusEnumApi = (typeof HogFlowStatusEnumApi)[keyof typeof HogFlowStatusEnumApi]

export const HogFlowStatusEnumApi = {
    Draft: 'draft',
    Active: 'active',
    Archived: 'archived',
} as const

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
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

export interface HogFlowConversionEventApi {
    /** Event/action filters for this conversion event, same shape as trigger filters: {events: [{id, name, type: 'events', properties?: [<cond>]}], actions?: [...], properties?: [<cond>]}. bytecode is compiled server-side. */
    filters: HogFunctionFiltersApi
}

export type HogFlowConversionApiFiltersItem = { [key: string]: unknown }

export interface HogFlowConversionApi {
    /** Property-based conversion conditions, as an ARRAY of property filters: [{key, value, operator, type: event|person|group}, ...]. Event-based goals do NOT go here — put them in 'events'. Empty array = any event within the window converts. */
    filters?: HogFlowConversionApiFiltersItem[]
    /** Event-based conversion goals: [{filters: {events: [{id, name, type: 'events'}], ...}}]. */
    events?: HogFlowConversionEventApi[]
    /**
     * Conversion window in minutes after a person enters the workflow. null = no explicit window.
     * @nullable
     */
    window_minutes?: number | null
    /** Compiled server-side from 'filters'. Do not set; ignored if sent. */
    bytecode?: unknown
}

/**
 * * `continue` - continue
 * * `branch` - branch
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
     *
     * * `continue` - continue
     * * `branch` - branch */
    type: HogFlowEdgeTypeEnumApi
    /** Required for type='branch'. conditional_branch: index into config.conditions[index]. wait_until_condition: use index:0 — it advances via the index:0 branch edge when it resolves (a condition match or an events entry firing). */
    index?: number
    /** Source action id. */
    from: string
}

/**
 * Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. Dictionary input values are template strings too — write booleans/numbers as single-expression templates ('{true}', '{42}'), which evaluate to the typed value. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same rules as delay). Continues when condition.filters match OR any events entry fires; each events entry must target at least one event or action. On resolution (a condition match or any events entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout falls through the 'continue' edge. exit: {reason}.
 */
export type HogFlowActionApiConfig =
    | { [key: string]: unknown }
    | {
          /** Property-based wait condition; continues when the person matches. A condition with no property filters is ignored — the wait then relies on 'events' and the max_wait_duration timeout. */
          condition?: {
              /** Property conditions, e.g. {properties: [{key, value, operator, type}]}. */
              filters?: HogFunctionFiltersApi | null
              /** Optional display name. */
              name?: string
          }
          /** Events to wait for: continues when ANY entry fires (OR'd with 'condition'). Each entry: {filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}. */
          events?: {
              /** Event/action filters; the workflow wakes when a matching event fires. Must target at least one event or action (entries targeting neither are dropped). */
              filters?: HogFunctionFiltersApi | null
              /** Optional display name. */
              name?: string
          }[]
          /** '<number><unit>' with unit m|h|d, e.g. '30m' (same rules as delay). */
          max_wait_duration: string
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
    /** On failure: continue (skip the action and proceed) or abort (stop the run).
     *
     * * `continue` - continue
     * * `abort` - abort */
    on_error?: OnErrorEnumApi | null
    /** Created at (epoch ms). Frontend-managed. */
    created_at?: number
    /** Updated at (epoch ms). Frontend-managed. */
    updated_at?: number
    /** Property filters gating this action. */
    filters?: HogFunctionFiltersApi | null
    /**
     * trigger | function | function_email | function_sms | delay | conditional_branch | wait_until_condition | wait_until_time_window | random_cohort_branch | exit.
     * @maxLength 100
     */
    type: string
    /** Type-specific config keyed by action type. trigger: {type: event|webhook|manual|batch|schedule|tracking_pixel, filters?}. filters shape: {events: [{id, name, type:'events', properties:[<cond>]}], properties:[<cond>], actions:[...], filter_test_accounts:<bool>}. <cond>: {key, value, operator, type: event|person|group}. function*: {template_id, inputs: {<key>: {value: <str>}}}. Wrap values in {value:...} to enable hog templating ({person.x}, {event.x}); flat strings won't interpolate. Dictionary input values are template strings too — write booleans/numbers as single-expression templates ('{true}', '{42}'), which evaluate to the typed value. delay: {delay_duration: '<number><unit>'} where unit is m|h|d. Fractions OK ('0.5m'=30s; seconds unsupported). Per-unit max m<=60, h<=24, d<=30; values above are SILENTLY CLAMPED. Max 30d. conditional_branch: {conditions: [{filters}, ...]}. Index N matches the 'branch' edge with index:N. wait_until_condition: {condition: {filters}, events?: [{filters: {events: [{id, name, type: 'events'}], actions?: [...]}, name?}], max_wait_duration: <duration>} (same rules as delay). Continues when condition.filters match OR any events entry fires; each events entry must target at least one event or action. On resolution (a condition match or any events entry firing) it advances via the 'branch' edge with index:0; the max_wait_duration timeout falls through the 'continue' edge. exit: {reason}. */
    config: HogFlowActionApiConfig
    /** Output variable definition for downstream actions. */
    output_variable?: unknown
}

/**
 * * `active` - Active
 * * `paused` - Paused
 * * `completed` - Completed
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
     *
     * * `active` - Active
     * * `paused` - Paused
     * * `completed` - Completed */
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
     *
     * * `draft` - Draft
     * * `active` - Active
     * * `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    readonly trigger: unknown
    /** Optional dedup/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window_minutes: minutes after entry. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side. */
    conversion?: HogFlowConversionApi | null
    /** exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').
     *
     * * `exit_on_conversion` - Conversion
     * * `exit_on_trigger_not_matched` - Trigger Not Matched
     * * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
     * * `exit_only_at_end` - Only At End */
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
     *
     * * `draft` - Draft
     * * `active` - Active
     * * `archived` - Archived */
    status?: HogFlowStatusEnumApi
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    readonly trigger?: unknown
    /** Optional dedup/throttle on an already-matched trigger: {hash: <HogQL template>, ttl: <seconds, 60-94608000>, threshold?: <int>}. Without threshold: fire once per hash, then suppress repeats within ttl (hash '{person.id}' = once per person per ttl). With threshold N: fire once per N matches of the same hash — a sampler, the 1st then every Nth. Throttles an already-qualifying trigger; it doesn't decide who enters. Server compiles bytecode from hash; omit to disable. */
    trigger_masking?: HogFlowMaskingApi | null
    /** Conversion goal. filters: ARRAY of property conditions [{key, value, operator, type: event|person|group}]; events: event-based goals [{filters: {events: [...]}}]; window_minutes: minutes after entry. Required for exit_on_conversion / exit_on_trigger_not_matched_or_conversion. bytecode compiled server-side. */
    conversion?: HogFlowConversionApi | null
    /** exit_only_at_end: only at exit node (default). exit_on_conversion: also on conversion (needs 'conversion'; silent no-op otherwise). exit_on_trigger_not_matched: also when trigger filter stops matching. exit_on_trigger_not_matched_or_conversion: both (needs 'conversion').
     *
     * * `exit_on_conversion` - Conversion
     * * `exit_on_trigger_not_matched` - Trigger Not Matched
     * * `exit_on_trigger_not_matched_or_conversion` - Trigger Not Matched Or Conversion
     * * `exit_only_at_end` - Only At End */
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

export interface MessageAssetApi {
    /** The workflow run this email was sent in. */
    invocation_id: string
    /** The email step (action node) within the workflow that sent this email. */
    action_id: string
    /** The workflow id that sent this email — used to navigate from a person's Emails tab back into the originating workflow. */
    function_id: string
    /** Human-readable workflow name for display. Empty when the workflow has been deleted; clients should fall back to function_id in that case. */
    function_name: string
    /** The batch run this email belongs to, for batch-triggered workflows. Empty for event-triggered runs. */
    parent_run_id: string
    /** Asset kind. Currently always 'email'. */
    kind: string
    /** The recipient's distinct_id. */
    distinct_id: string
    /** The recipient's person UUID, if resolved. */
    person_id: string
    /** The recipient email address. */
    recipient: string
    /** The email subject line. */
    subject: string
    /** Delivery status at capture time. Currently always 'sent'. */
    status: string
    /** When the email was sent. */
    sent_at: string
}

/**
 * * `waiting` - Waiting
 * * `queued` - Queued
 * * `active` - Active
 * * `completed` - Completed
 * * `cancelled` - Cancelled
 * * `failed` - Failed
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
     *
     * * `waiting` - Waiting
     * * `queued` - Queued
     * * `active` - Active
     * * `completed` - Completed
     * * `cancelled` - Cancelled
     * * `failed` - Failed */
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
 * * `update_action` - update_action
 * * `add_action` - add_action
 * * `remove_action` - remove_action
 * * `add_edge` - add_edge
 * * `remove_edge` - remove_edge
 * * `replace_action_edges` - replace_action_edges
 */
export type HogFlowGraphOperationOpEnumApi =
    (typeof HogFlowGraphOperationOpEnumApi)[keyof typeof HogFlowGraphOperationOpEnumApi]

export const HogFlowGraphOperationOpEnumApi = {
    UpdateAction: 'update_action',
    AddAction: 'add_action',
    RemoveAction: 'remove_action',
    AddEdge: 'add_edge',
    RemoveEdge: 'remove_edge',
    ReplaceActionEdges: 'replace_action_edges',
} as const

export interface HogFlowGraphOperationApi {
    /** Graph edit. update_action {id, patch}: deep-merge patch into the action's fields (a null leaf deletes that key) — the surgical path for tweaking one config value. add_action {action}: append a full action node. remove_action {id}: delete a node and reconnect its incoming edges to its first outgoer. add_edge {edge} / remove_edge {edge}: add or delete one edge. replace_action_edges {id, edges}: replace this action's outgoing edges with the given set (use when adding/removing branch conditions); incoming edges are left intact.
     *
     * * `update_action` - update_action
     * * `add_action` - add_action
     * * `remove_action` - remove_action
     * * `add_edge` - add_edge
     * * `remove_edge` - remove_edge
     * * `replace_action_edges` - replace_action_edges */
    op: HogFlowGraphOperationOpEnumApi
    /** Action id. Required for update_action, remove_action, replace_action_edges. */
    id?: string
    /** update_action only. Partial action fields, deep-merged into the existing action; a null leaf deletes that key. e.g. {config: {inputs: {subject: {value: 'Hi'}}}} changes only that input. */
    patch?: unknown
    /** add_action only. A full action node {id, name, type, config, ...}; same shape as in actions. */
    action?: unknown
    /** add_edge / remove_edge only. The edge {from, to, type, index?}. */
    edge?: HogFlowEdgeApi
    /** replace_action_edges only. The complete set of the action's outgoing edges; incoming edges are preserved. */
    edges?: HogFlowEdgeApi[]
}

export interface PatchedHogFlowGraphUpdateApi {
    /** Ordered graph edits applied atomically to a draft workflow: the stored graph is read, the ops are applied in order, the result is fully validated, and it's saved only if valid — otherwise the workflow is unchanged. Reference nodes/edges by id so you never resend the whole graph. The full updated workflow is returned. */
    operations?: HogFlowGraphOperationApi[]
}

export interface HogInvocationResultApi {
    invocation_id: string
    status: string
    error_kind: string
    error_message: string
    distinct_id: string
    person_id: string
    scheduled_at: string
    /** @nullable */
    started_at: string | null
    /** @nullable */
    finished_at: string | null
    /** @nullable */
    duration_ms: number | null
    attempts: number
    is_retry: boolean
}

/**
 * The triggering payload (event/person/groups) the run executed against, as a JSON object.
 */
export type HogInvocationResultDetailApiInvocationGlobals = { [key: string]: unknown }

export interface HogInvocationResultDetailApi {
    /** The triggering payload (event/person/groups) the run executed against, as a JSON object. */
    invocation_globals: HogInvocationResultDetailApiInvocationGlobals
    invocation_id: string
    status: string
    error_kind: string
    error_message: string
    distinct_id: string
    person_id: string
    scheduled_at: string
    /** @nullable */
    started_at: string | null
    /** @nullable */
    finished_at: string | null
    /** @nullable */
    duration_ms: number | null
    attempts: number
    is_retry: boolean
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
    /** Start execution from this action ID instead of the trigger. Each test run executes a single node and returns the next action id. */
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
 * * `running` - running
 * * `succeeded` - succeeded
 * * `failed` - failed
 */
export type HogInvocationRerunFilterStatusEnumApi =
    (typeof HogInvocationRerunFilterStatusEnumApi)[keyof typeof HogInvocationRerunFilterStatusEnumApi]

export const HogInvocationRerunFilterStatusEnumApi = {
    Running: 'running',
    Succeeded: 'succeeded',
    Failed: 'failed',
} as const

/**
 * Filter shape for the rerun endpoint. `window_start`/`window_end` are required.
 */
export interface HogInvocationRerunFilterApi {
    /** Inclusive lower bound on `scheduled_at` (UTC). */
    window_start: string
    /** Exclusive upper bound on `scheduled_at` (UTC). */
    window_end: string
    /** Restrict to invocations whose latest status is one of these. Defaults to ['failed']. */
    status?: HogInvocationRerunFilterStatusEnumApi[]
    /** Restrict to invocations whose error_kind matches one of these (e.g. 'http_5xx', 'timeout'). */
    error_kind?: string[]
    /**
     * Skip invocations that have already been attempted this many times or more.
     * @minimum 1
     * @maximum 255
     */
    max_attempts?: number
    /**
     * Maximum number of invocations to rerun in this request. Server-side cap is 10000.
     * @minimum 1
     * @maximum 10000
     */
    max_count?: number
    /**
     * Optional restriction to specific invocation IDs within the window. Capped at 10000 per request. Always combined with `window_start`/`window_end` so the ClickHouse query can be partition-pruned.
     * @maxItems 10000
     */
    invocation_ids?: string[]
}

/**
 * Rerun invocations of a hog function or hog flow from their stored payloads.
 */
export interface HogInvocationRerunRequestApi {
    /** Required. `window_start` / `window_end` pin the query to a small set of date partitions on the `hog_invocation_results` table. Optional `invocation_ids` restricts to specific invocations within that window. */
    filter: HogInvocationRerunFilterApi
}

/**
 * Response from the rerun endpoint. The endpoint only enqueues a wrapper
 * job onto the cyclotron `rerun` queue — the actual ClickHouse paging and
 * re-enqueue work happens asynchronously in the `cdp-rerun-worker` service.
 * Use `rerun_job_id` to look up progress on the wrapper job later.
 */
export interface HogInvocationRerunResponseApi {
    /** ID of the cyclotron wrapper job that will run the rerun. Use this to poll status. */
    rerun_job_id: string
    /** Always 0 — rerun runs asynchronously. Kept for response shape stability. */
    queued_count: number
    /** Always 0 — rerun runs asynchronously. Kept for response shape stability. */
    skipped_count: number
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
     *
     * * `active` - Active
     * * `paused` - Paused
     * * `completed` - Completed */
    readonly status?: HogFlowScheduleStatusEnumApi
    /**
     * Next scheduled fire time, computed by the scheduler.
     * @nullable
     */
    readonly next_run_at?: string | null
    readonly created_at?: string
    readonly updated_at?: string
}

export interface WorkflowStatsRowApi {
    /** The workflow these counts are for. */
    workflow_id: string
    /** Successful invocations in the window. */
    succeeded: number
    /** Failed invocations in the window. */
    failed: number
}

/**
 * Property filters to apply
 */
export type BlastRadiusRequestApiFilters = { [key: string]: unknown }

/**
 * * `email` - email
 */
export type DedupeKeyEnumApi = (typeof DedupeKeyEnumApi)[keyof typeof DedupeKeyEnumApi]

export const DedupeKeyEnumApi = {
    Email: 'email',
} as const

export interface BlastRadiusRequestApi {
    /** Property filters to apply */
    filters: BlastRadiusRequestApiFilters
    /**
     * Group type index for group-based targeting
     * @nullable
     */
    group_type_index?: number | null
    /** When 'email', count unique email addresses instead of persons, matching how batch email sends deduplicate recipients.
     *
     * * `email` - email */
    dedupe_key?: DedupeKeyEnumApi | null
}

export interface BlastRadiusApi {
    /** Number of users matching the filters */
    affected: number
    /** Total number of users */
    total: number
    /** Maximum allowed audience size for batch triggers for this team. */
    limit: number
    /** The dedupe key that was actually applied to 'affected'. 'email' means it counts unique email addresses; null means it counts persons.
     *
     * * `email` - email */
    dedupe_key: DedupeKeyEnumApi | null
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
     * * `active` - Active
     * * `archived` - Archived
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

export type HogFlowsAssetsRetrieveParams = {
    /**
     * Only return assets sent by this email step (action node id) — used to drill in from a step's metric.
     * @minLength 1
     */
    action_id?: string
    /**
     * Start of the time range, matched on sent time. Relative ('-30d', '-24h') or ISO 8601. Defaults to -30d (the retention window) — bounds the ClickHouse partition scan.
     * @minLength 1
     */
    after?: string
    /**
     * End of the time range, matched on sent time. Same format as 'after'. Defaults to now.
     * @minLength 1
     */
    before?: string
    /**
     * Only return assets sent to this distinct_id.
     * @minLength 1
     */
    distinct_id?: string
    /**
     * Only return the asset for this specific workflow run — used to deep-link from a single log entry to the email it sent. Returns 0 rows when the send had no captured asset (text-only, kill-switch off, or standalone email).
     * @minLength 1
     */
    invocation_id?: string
    /**
     * Maximum number of assets to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of assets to skip, for pagination.
     * @minimum 0
     */
    offset?: number
    /**
     * Only return assets for this batch run (HogFlowBatchJob id). Pass an empty string to return only event-triggered (non-batch) assets; omit to return all.
     */
    parent_run_id?: string
    /**
     * Case-insensitive substring match on recipient email or subject.
     * @minLength 1
     */
    search?: string
}

export type HogFlowsAssetContentRetrieveParams = {
    /**
     * The email step (action node) that sent the email. Defaults to empty for standalone email sends.
     */
    action_id?: string
    /**
     * The workflow run the email was sent in.
     * @minLength 1
     */
    invocation_id: string
}

export type HogFlowsInvocationResultsRetrieveParams = {
    /**
     * Start of the time range, matched on scheduled time. Relative ('-7d', '-24h') or ISO 8601. Defaults to -7d — bounds the ClickHouse partition scan, so widen it explicitly for older runs.
     * @minLength 1
     */
    after?: string
    /**
     * End of the time range, matched on scheduled time. Same format as 'after'. Defaults to now.
     * @minLength 1
     */
    before?: string
    /**
     * Only return invocations triggered for this distinct_id (the person the run executed for).
     * @minLength 1
     */
    distinct_id?: string
    /**
     * Maximum number of invocations to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Comma-separated invocation statuses to include, e.g. 'failed' or 'success,failed'.
     * @minLength 1
     */
    status?: string
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
     *
     * * `name` - name
     * * `kind` - kind
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
     *
     * * `hour` - hour
     * * `day` - day
     * * `week` - week
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
     *
     * * `name` - name
     * * `kind` - kind
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
     *
     * * `hour` - hour
     * * `day` - day
     * * `week` - week
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

export type HogFlowsMetricsGlobalRetrieveParams = {
    /**
     * Start of the window, matched on metric time. Relative ('-7d', '-24h') or ISO 8601. Defaults to -7d.
     * @minLength 1
     */
    after?: string
    /**
     * End of the window. Same format as 'after'. Defaults to now.
     * @minLength 1
     */
    before?: string
}
