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
 * @nullable
 */
export type ErrorTrackingAssignmentRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null

export interface ErrorTrackingAssignmentRuleApi {
    readonly id: string
    filters: unknown
    /** @nullable */
    readonly assignee: ErrorTrackingAssignmentRuleApiAssignee
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
    disabled_data?: unknown
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedErrorTrackingAssignmentRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingAssignmentRuleApi[]
}

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

export const PropertyOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Gte: 'gte',
    Lt: 'lt',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
    Between: 'between',
    NotBetween: 'not_between',
    Min: 'min',
    Max: 'max',
    In: 'in',
    NotIn: 'not_in',
    IsCleanedPathExact: 'is_cleaned_path_exact',
    FlagEvaluatesTo: 'flag_evaluates_to',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export interface EventPropertyFilterApi {
    key: string
    label?: string | null
    operator?: PropertyOperatorApi | null
    /** Event properties */
    type?: 'event'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: 'person'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export interface ElementPropertyFilterApi {
    key: Key10Api
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'element'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface EventMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'event_metadata'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface SessionPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'session'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface CohortPropertyFilterApi {
    cohort_name?: string | null
    key?: 'id'
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: 'cohort'
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export interface RecordingPropertyFilterApi {
    key: DurationTypeApi | string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'recording'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface LogEntryPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'log_entry'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null

export interface GroupPropertyFilterApi {
    group_key_names?: GroupPropertyFilterApiGroupKeyNames
    group_type_index?: number | null
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'group'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FeaturePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: 'feature'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface FlagPropertyFilterApi {
    /** The key should be the flag ID */
    key: string
    label?: string | null
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator?: 'flag_evaluates_to'
    /** Feature flag dependency */
    type?: 'flag'
    /** The value can be true, false, or a variant name */
    value: boolean | string
}

export interface HogQLPropertyFilterApi {
    key: string
    label?: string | null
    type?: 'hogql'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export const EmptyPropertyFilterApiValue = {
    type: 'empty',
} as const
export type EmptyPropertyFilterApi = typeof EmptyPropertyFilterApiValue

export interface DataWarehousePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'data_warehouse_person_property'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface ErrorTrackingIssueFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'error_tracking_issue'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

export const LogPropertyFilterTypeApi = {
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
} as const

export interface LogPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: LogPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type SpanPropertyFilterTypeApi = (typeof SpanPropertyFilterTypeApi)[keyof typeof SpanPropertyFilterTypeApi]

export const SpanPropertyFilterTypeApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export interface SpanPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type: SpanPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'revenue_analytics'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface WorkflowVariablePropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'workflow_variable'
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export interface PropertyGroupFilterValueApi {
    type: FilterLogicalOperatorApi
    values: (
        | PropertyGroupFilterValueApi
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | ElementPropertyFilterApi
        | EventMetadataPropertyFilterApi
        | SessionPropertyFilterApi
        | CohortPropertyFilterApi
        | RecordingPropertyFilterApi
        | LogEntryPropertyFilterApi
        | GroupPropertyFilterApi
        | FeaturePropertyFilterApi
        | FlagPropertyFilterApi
        | HogQLPropertyFilterApi
        | EmptyPropertyFilterApi
        | DataWarehousePropertyFilterApi
        | DataWarehousePersonPropertyFilterApi
        | ErrorTrackingIssueFilterApi
        | LogPropertyFilterApi
        | SpanPropertyFilterApi
        | RevenueAnalyticsPropertyFilterApi
        | WorkflowVariablePropertyFilterApi
    )[]
}

/**
 * * `user` - user
 * `role` - role
 */
export type AssigneeTypeEnumApi = (typeof AssigneeTypeEnumApi)[keyof typeof AssigneeTypeEnumApi]

export const AssigneeTypeEnumApi = {
    User: 'user',
    Role: 'role',
} as const

export interface ErrorTrackingAssignmentRuleAssigneeRequestApi {
    /** Assignee type. Use `user` for a user ID or `role` for a role UUID.

  * `user` - user
  * `role` - role */
    type: AssigneeTypeEnumApi
    /** User ID when `type` is `user`, or role UUID when `type` is `role`. */
    id: number | string
}

export interface ErrorTrackingAssignmentRuleCreateRequestApi {
    /** Property-group filters that define when this rule matches incoming error events. */
    filters: PropertyGroupFilterValueApi
    /** User or role to assign matching issues to. */
    assignee: ErrorTrackingAssignmentRuleAssigneeRequestApi
}

export interface ErrorTrackingAssignmentRuleUpdateRequestApi {
    /** Property-group filters that define when this rule matches incoming error events. */
    filters?: PropertyGroupFilterValueApi | null
    /** User or role to assign matching issues to. */
    assignee?: ErrorTrackingAssignmentRuleAssigneeRequestApi | null
}

export interface PatchedErrorTrackingAssignmentRuleUpdateRequestApi {
    /** Property-group filters that define when this rule matches incoming error events. */
    filters?: PropertyGroupFilterValueApi | null
    /** User or role to assign matching issues to. */
    assignee?: ErrorTrackingAssignmentRuleAssigneeRequestApi | null
}

/**
 * @nullable
 */
export type PatchedErrorTrackingAssignmentRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null

export interface PatchedErrorTrackingAssignmentRuleApi {
    readonly id?: string
    filters?: unknown
    /** @nullable */
    readonly assignee?: PatchedErrorTrackingAssignmentRuleApiAssignee
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
    disabled_data?: unknown
    readonly created_at?: string
    readonly updated_at?: string
}

export interface ErrorTrackingExternalReferenceIntegrationResultApi {
    readonly id: number
    readonly kind: string
    readonly display_name: string
}

export interface ErrorTrackingExternalReferenceResultApi {
    readonly id: string
    readonly integration: ErrorTrackingExternalReferenceIntegrationResultApi
    integration_id: number
    config: unknown
    issue: string
    readonly external_url: string
}

export interface PaginatedErrorTrackingExternalReferenceResultListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingExternalReferenceResultApi[]
}

export interface ErrorTrackingFingerprintApi {
    readonly id: string
    readonly fingerprint: string
    readonly issue_id: string
    readonly created_at: string
}

export interface PaginatedErrorTrackingFingerprintListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingFingerprintApi[]
}

export interface GitProviderFileLinkResolveResponseApi {
    /** Whether a matching file URL was found. */
    found: boolean
    /** Resolved URL for the matching file. */
    url?: string
    /** Error message when input parameters are invalid. */
    error?: string
}

/**
 * @nullable
 */
export type ErrorTrackingGroupingRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null

/**
 * Issue linked to this rule
 * @nullable
 */
export type ErrorTrackingGroupingRuleApiIssue = { [key: string]: string } | null

export interface ErrorTrackingGroupingRuleApi {
    readonly id: string
    filters: unknown
    /** @nullable */
    readonly assignee: ErrorTrackingGroupingRuleApiAssignee
    /** @nullable */
    description?: string | null
    /**
     * Issue linked to this rule
     * @nullable
     */
    readonly issue: ErrorTrackingGroupingRuleApiIssue
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
    disabled_data?: unknown
    readonly created_at: string
    readonly updated_at: string
}

export interface ErrorTrackingGroupingRuleListResponseApi {
    results: ErrorTrackingGroupingRuleApi[]
}

export interface ErrorTrackingGroupingRuleAssigneeRequestApi {
    /** Assignee type. Use `user` for a user ID or `role` for a role UUID.

  * `user` - user
  * `role` - role */
    type: AssigneeTypeEnumApi
    /** User ID when `type` is `user`, or role UUID when `type` is `role`. */
    id: number | string
}

export interface ErrorTrackingGroupingRuleCreateRequestApi {
    /** Property-group filters that define which exceptions should be grouped into the same issue. */
    filters: PropertyGroupFilterValueApi
    /** Optional user or role to assign to issues created by this grouping rule. */
    assignee?: ErrorTrackingGroupingRuleAssigneeRequestApi | null
    /**
     * Optional human-readable description of what this grouping rule is for.
     * @nullable
     */
    description?: string | null
}

/**
 * @nullable
 */
export type PatchedErrorTrackingGroupingRuleApiAssignee = {
    readonly type?: 'user' | 'role'
    readonly id?: number | string
} | null

/**
 * Issue linked to this rule
 * @nullable
 */
export type PatchedErrorTrackingGroupingRuleApiIssue = { [key: string]: string } | null

export interface PatchedErrorTrackingGroupingRuleApi {
    readonly id?: string
    filters?: unknown
    /** @nullable */
    readonly assignee?: PatchedErrorTrackingGroupingRuleApiAssignee
    /** @nullable */
    description?: string | null
    /**
     * Issue linked to this rule
     * @nullable
     */
    readonly issue?: PatchedErrorTrackingGroupingRuleApiIssue
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
    disabled_data?: unknown
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * * `archived` - Archived
 * `active` - Active
 * `resolved` - Resolved
 * `pending_release` - Pending release
 * `suppressed` - Suppressed
 */
export type ErrorTrackingIssueFullStatusEnumApi =
    (typeof ErrorTrackingIssueFullStatusEnumApi)[keyof typeof ErrorTrackingIssueFullStatusEnumApi]

export const ErrorTrackingIssueFullStatusEnumApi = {
    Archived: 'archived',
    Active: 'active',
    Resolved: 'resolved',
    PendingRelease: 'pending_release',
    Suppressed: 'suppressed',
} as const

export interface ErrorTrackingIssueAssignmentApi {
    readonly id: number | string | null
    readonly type: string
}

/**
 * @nullable
 */
export type ErrorTrackingIssueFullApiCohort = {
    readonly id?: number
    readonly name?: string
} | null

export interface ErrorTrackingIssueFullApi {
    readonly id: string
    status?: ErrorTrackingIssueFullStatusEnumApi
    /** @nullable */
    name?: string | null
    /** @nullable */
    description?: string | null
    first_seen: string
    assignee: ErrorTrackingIssueAssignmentApi
    external_issues: ErrorTrackingExternalReferenceResultApi[]
    /** @nullable */
    readonly cohort: ErrorTrackingIssueFullApiCohort
}

export interface PaginatedErrorTrackingIssueFullListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingIssueFullApi[]
}

/**
 * @nullable
 */
export type PatchedErrorTrackingIssueFullApiCohort = {
    readonly id?: number
    readonly name?: string
} | null

export interface PatchedErrorTrackingIssueFullApi {
    readonly id?: string
    status?: ErrorTrackingIssueFullStatusEnumApi
    /** @nullable */
    name?: string | null
    /** @nullable */
    description?: string | null
    first_seen?: string
    assignee?: ErrorTrackingIssueAssignmentApi
    external_issues?: ErrorTrackingExternalReferenceResultApi[]
    /** @nullable */
    readonly cohort?: PatchedErrorTrackingIssueFullApiCohort
}

export interface ErrorTrackingIssueMergeRequestApi {
    /** IDs of the issues to merge into the current issue. */
    ids: string[]
}

export interface ErrorTrackingIssueMergeResponseApi {
    /** Whether the merge completed successfully. */
    success: boolean
}

export interface ErrorTrackingIssueSplitFingerprintApi {
    /** Fingerprint to split into a new issue. */
    fingerprint: string
    /** Optional name for the new issue created from this fingerprint. */
    name?: string
    /** Optional description for the new issue created from this fingerprint. */
    description?: string
}

export interface ErrorTrackingIssueSplitRequestApi {
    /** Fingerprints to split into new issues. Each fingerprint becomes its own new issue. */
    fingerprints?: ErrorTrackingIssueSplitFingerprintApi[]
}

export interface ErrorTrackingIssueSplitResponseApi {
    /** Whether the split completed successfully. */
    success: boolean
    /** IDs of the new issues created by the split. */
    new_issue_ids: string[]
}

export interface ErrorTrackingDateRangeApi {
    /** Start of the date range as an ISO timestamp or relative date such as -7d. Defaults to -7d. */
    date_from?: string
    /**
     * End of the date range as an ISO timestamp or relative date. Defaults to now when omitted.
     * @nullable
     */
    date_to?: string | null
}

export interface ErrorTrackingIssueQueryRequestApi {
    /** Error tracking issue ID. */
    issueId: string
    /** Date range for issue impact and latest-event metadata. Defaults to the last 7 days. */
    dateRange?: ErrorTrackingDateRangeApi
    /** When true, exclude internal/test account data from results. Defaults to true. */
    filterTestAccounts?: boolean
    /**
     * Volume buckets. Maximum 200.
     * @minimum 0
     * @maximum 200
     */
    volumeResolution?: number
    /** Set true to include a compact numeric occurrence sparkline. Defaults to false. */
    includeSparkline?: boolean
}

export interface ErrorTrackingAssigneeResponseApi {
    /** Assignee user ID or role UUID. */
    id?: string | number | null
    /**
     * Assignee type.
     * @nullable
     */
    type?: string | null
}

export interface ErrorTrackingVolumeBucketApi {
    /** Bucket timestamp label. */
    label: string
    /**
     * Occurrence count for the bucket.
     * @nullable
     */
    value?: number | null
}

export interface ErrorTrackingAggregationsApi {
    /** Exception occurrence count. */
    occurrences?: number
    /** Unique user count. */
    users?: number
    /** Unique session count. */
    sessions?: number
    /** Occurrence counts per volume bucket. */
    volumeRange?: number[]
    /** Labeled volume buckets. */
    volume_buckets?: ErrorTrackingVolumeBucketApi[]
}

export interface ErrorTrackingTopFrameApi {
    /** Frame function name. */
    function?: string
    /** Frame source, filename, or module. */
    source?: string
    /** Line number. */
    line?: number
    /** Column number. */
    column?: number
    /** Whether the frame is an application frame. */
    in_app?: boolean
}

export interface ErrorTrackingLatestReleaseApi {
    /** Release version. */
    version?: string
    /** Release project/library. */
    project?: string
    /** Release timestamp. */
    timestamp?: string
    /** Git commit ID. */
    commit_id?: string
    /** Git branch. */
    branch?: string
    /** Git repository name. */
    repo_name?: string
}

export interface ErrorTrackingImpactApi {
    /** Exception occurrence count. */
    occurrences?: number
    /** Unique user count. */
    users?: number
    /** Unique session count. */
    sessions?: number
}

export interface ErrorTrackingIssueDetailApi {
    /** Error tracking issue ID. */
    id: string
    /**
     * Issue name.
     * @nullable
     */
    name?: string | null
    /**
     * Issue description.
     * @nullable
     */
    description?: string | null
    /** Issue status. */
    status?: string
    /**
     * First seen timestamp.
     * @nullable
     */
    first_seen?: string | null
    /**
     * Last seen timestamp.
     * @nullable
     */
    last_seen?: string | null
    /**
     * SDK/library associated with the issue.
     * @nullable
     */
    library?: string | null
    /**
     * Top source/file associated with the issue.
     * @nullable
     */
    source?: string | null
    /** Issue assignee. */
    assignee?: ErrorTrackingAssigneeResponseApi | null
    /** Aggregate counts. */
    aggregations?: ErrorTrackingAggregationsApi | null
    /**
     * Top function associated with the issue.
     * @nullable
     */
    function?: string | null
    /** Top in_app application frame. */
    top_in_app_frame?: ErrorTrackingTopFrameApi
    /** Latest release metadata. */
    latest_release?: ErrorTrackingLatestReleaseApi
    /** Compact impact counts. */
    impact?: ErrorTrackingImpactApi
    /** Optional compact occurrence sparkline. */
    sparkline?: number[]
}

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `icontains` - icontains
 * `not_icontains` - not_icontains
 * `regex` - regex
 * `not_regex` - not_regex
 * `gt` - gt
 * `lt` - lt
 * `gte` - gte
 * `lte` - lte
 * `is_set` - is_set
 * `is_not_set` - is_not_set
 * `is_date_exact` - is_date_exact
 * `is_date_after` - is_date_after
 * `is_date_before` - is_date_before
 * `in` - in
 * `not_in` - not_in
 */
export type PropertyItemOperatorEnumApi = (typeof PropertyItemOperatorEnumApi)[keyof typeof PropertyItemOperatorEnumApi]

export const PropertyItemOperatorEnumApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Lt: 'lt',
    Gte: 'gte',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateAfter: 'is_date_after',
    IsDateBefore: 'is_date_before',
    In: 'in',
    NotIn: 'not_in',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * * `event` - event
 * `event_metadata` - event_metadata
 * `feature` - feature
 * `person` - person
 * `cohort` - cohort
 * `element` - element
 * `static-cohort` - static-cohort
 * `dynamic-cohort` - dynamic-cohort
 * `precalculated-cohort` - precalculated-cohort
 * `group` - group
 * `recording` - recording
 * `log_entry` - log_entry
 * `behavioral` - behavioral
 * `session` - session
 * `hogql` - hogql
 * `data_warehouse` - data_warehouse
 * `data_warehouse_person_property` - data_warehouse_person_property
 * `error_tracking_issue` - error_tracking_issue
 * `log` - log
 * `log_attribute` - log_attribute
 * `log_resource_attribute` - log_resource_attribute
 * `span` - span
 * `span_attribute` - span_attribute
 * `span_resource_attribute` - span_resource_attribute
 * `revenue_analytics` - revenue_analytics
 * `flag` - flag
 * `workflow_variable` - workflow_variable
 */
export type PropertyFilterTypeEnumApi = (typeof PropertyFilterTypeEnumApi)[keyof typeof PropertyFilterTypeEnumApi]

export const PropertyFilterTypeEnumApi = {
    Event: 'event',
    EventMetadata: 'event_metadata',
    Feature: 'feature',
    Person: 'person',
    Cohort: 'cohort',
    Element: 'element',
    StaticCohort: 'static-cohort',
    DynamicCohort: 'dynamic-cohort',
    PrecalculatedCohort: 'precalculated-cohort',
    Group: 'group',
    Recording: 'recording',
    LogEntry: 'log_entry',
    Behavioral: 'behavioral',
    Session: 'session',
    Hogql: 'hogql',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
    ErrorTrackingIssue: 'error_tracking_issue',
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
    RevenueAnalytics: 'revenue_analytics',
    Flag: 'flag',
    WorkflowVariable: 'workflow_variable',
} as const

export interface PropertyItemApi {
    /** Key of the property you're filtering on. For example `email` or `$current_url` */
    key: string
    /** Value of your filter. For example `test@example.com` or `https://example.com/test/`. Can be an array for an OR query, like `["test@example.com","ok@example.com"]` */
    value: string | number | boolean | (string | number)[]
    operator?: PropertyItemOperatorEnumApi | BlankEnumApi | NullEnumApi | null
    type?: PropertyFilterTypeEnumApi | BlankEnumApi
}

/**
 * * `ASC` - ASC
 * `DESC` - DESC
 */
export type OrderDirectionEnumApi = (typeof OrderDirectionEnumApi)[keyof typeof OrderDirectionEnumApi]

export const OrderDirectionEnumApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

/**
 * * `summary` - summary
 * `stack` - stack
 * `raw` - raw
 */
export type VerbosityEnumApi = (typeof VerbosityEnumApi)[keyof typeof VerbosityEnumApi]

export const VerbosityEnumApi = {
    Summary: 'summary',
    Stack: 'stack',
    Raw: 'raw',
} as const

export interface ErrorTrackingIssueEventsQueryRequestApi {
    /** Error tracking issue ID. */
    issueId: string
    /** Date range for sampled exception events. Defaults to the last 7 days. */
    dateRange?: ErrorTrackingDateRangeApi
    /** When true, exclude internal/test account data from results. Defaults to true. */
    filterTestAccounts?: boolean
    /** Advanced flat AND property filters applied to sampled events. HogQL filters are rejected. */
    filterGroup?: PropertyItemApi[]
    /**
     * Search exception types, exception values, and current URL among sampled events.
     * @maxLength 500
     */
    searchQuery?: string
    /** Timestamp sort direction. Defaults to DESC.

* `ASC` - ASC
* `DESC` - DESC */
    orderDirection?: OrderDirectionEnumApi
    /**
     * Page size.
     * @minimum 1
     * @maximum 20
     */
    limit?: number
    /**
     * Pagination offset.
     * @minimum 0
     */
    offset?: number
    /** Controls exception detail size: summary, stack, or raw. Defaults to summary.

* `summary` - summary
* `stack` - stack
* `raw` - raw */
    verbosity?: VerbosityEnumApi
    /** When true, include only stack frames marked in_app. Defaults to true. */
    onlyAppFrames?: boolean
}

/**
 * Normalized sampled exception event properties.
 */
export type ErrorTrackingEventApiProperties = { [key: string]: unknown }

export interface ErrorTrackingEventApi {
    /** Event UUID. */
    uuid?: string
    /** Event distinct ID. */
    distinct_id?: string
    /** Event timestamp. */
    timestamp?: string
    /** Normalized sampled exception event properties. */
    properties?: ErrorTrackingEventApiProperties
}

export interface ErrorTrackingIssueEventsResponseApi {
    /** Sampled exception events. */
    results: ErrorTrackingEventApi[]
    /** Whether more results are available. */
    hasMore: boolean
    /** Page size. */
    limit: number
    /** Current offset. */
    offset: number
    /** Offset to fetch the next page when hasMore is true. */
    nextOffset?: number
}

/**
 * * `archived` - archived
 * `active` - active
 * `resolved` - resolved
 * `pending_release` - pending_release
 * `suppressed` - suppressed
 * `all` - all
 */
export type ErrorTrackingIssuesListQueryRequestStatusEnumApi =
    (typeof ErrorTrackingIssuesListQueryRequestStatusEnumApi)[keyof typeof ErrorTrackingIssuesListQueryRequestStatusEnumApi]

export const ErrorTrackingIssuesListQueryRequestStatusEnumApi = {
    Archived: 'archived',
    Active: 'active',
    Resolved: 'resolved',
    PendingRelease: 'pending_release',
    Suppressed: 'suppressed',
    All: 'all',
} as const

export interface ErrorTrackingAssigneeApi {
    /** User ID or role UUID to filter by. */
    id: string | number
    /** Assignee target type: user or role.

* `user` - user
* `role` - role */
    type: AssigneeTypeEnumApi
}

/**
 * * `last_seen` - last_seen
 * `first_seen` - first_seen
 * `occurrences` - occurrences
 * `users` - users
 * `sessions` - sessions
 */
export type ErrorTrackingIssueOrderByEnumApi =
    (typeof ErrorTrackingIssueOrderByEnumApi)[keyof typeof ErrorTrackingIssueOrderByEnumApi]

export const ErrorTrackingIssueOrderByEnumApi = {
    LastSeen: 'last_seen',
    FirstSeen: 'first_seen',
    Occurrences: 'occurrences',
    Users: 'users',
    Sessions: 'sessions',
} as const

export interface ErrorTrackingIssuesListQueryRequestApi {
    /** Date range for issue aggregates. Defaults to the last 7 days. */
    dateRange?: ErrorTrackingDateRangeApi
    /** Filter by issue status. Defaults to active.

* `archived` - archived
* `active` - active
* `resolved` - resolved
* `pending_release` - pending_release
* `suppressed` - suppressed
* `all` - all */
    status?: ErrorTrackingIssuesListQueryRequestStatusEnumApi
    /** Filter by issue assignee. Omit to include all assignees. */
    assignee?: ErrorTrackingAssigneeApi | null
    /** When true, exclude internal/test account data from results. Defaults to true. */
    filterTestAccounts?: boolean
    /**
     * Free-text search across exception types, values, stack frames, and email fields.
     * @maxLength 500
     */
    searchQuery?: string
    /** Advanced flat AND property filters. Prefer typed shortcut fields when they fit. HogQL filters are rejected. */
    filterGroup?: PropertyItemApi[]
    /** Field used to sort issues. Defaults to occurrences.

* `last_seen` - last_seen
* `first_seen` - first_seen
* `occurrences` - occurrences
* `users` - users
* `sessions` - sessions */
    orderBy?: ErrorTrackingIssueOrderByEnumApi
    /** Sort direction. Defaults to DESC.

* `ASC` - ASC
* `DESC` - DESC */
    orderDirection?: OrderDirectionEnumApi
    /**
     * Page size.
     * @minimum 1
     * @maximum 100
     */
    limit?: number
    /**
     * Pagination offset.
     * @minimum 0
     */
    offset?: number
    /**
     * Number of volume buckets. Defaults to 0 for compact aggregate counts.
     * @minimum 0
     * @maximum 200
     */
    volumeResolution?: number
    /** Filter by SDK/library value from event $lib, for example posthog-js. */
    library?: string | string[]
    /**
     * Filter by exact release ID, version, or git commit ID captured in $exception_releases.
     * @maxLength 500
     */
    release?: string
    /** Filter by exact exception fingerprint hash, not fuzzy search. */
    fingerprint?: string | string[]
    /**
     * Search user/email text.
     * @maxLength 500
     */
    user?: string
    /** Filter by exact PostHog person UUID. */
    personId?: string
    /**
     * Filter by current URL substring.
     * @maxLength 1000
     */
    url?: string
    /**
     * Search stack-frame source/file path text.
     * @maxLength 1000
     */
    filePath?: string
}

export interface ErrorTrackingIssueListItemApi {
    /** Error tracking issue ID. */
    id: string
    /**
     * Issue name.
     * @nullable
     */
    name?: string | null
    /**
     * Issue description.
     * @nullable
     */
    description?: string | null
    /** Issue status. */
    status?: string
    /**
     * First seen timestamp.
     * @nullable
     */
    first_seen?: string | null
    /**
     * Last seen timestamp.
     * @nullable
     */
    last_seen?: string | null
    /**
     * SDK/library associated with the issue.
     * @nullable
     */
    library?: string | null
    /**
     * Top source/file associated with the issue.
     * @nullable
     */
    source?: string | null
    /** Issue assignee. */
    assignee?: ErrorTrackingAssigneeResponseApi | null
    /** Aggregate counts. */
    aggregations?: ErrorTrackingAggregationsApi | null
}

export interface ErrorTrackingIssuesListResponseApi {
    /** Issue rows. */
    results: ErrorTrackingIssueListItemApi[]
    /** Whether more results are available. */
    hasMore: boolean
    /** Page size. */
    limit: number
    /** Current offset. */
    offset: number
    /** Offset to fetch the next page when hasMore is true. */
    nextOffset?: number
}

export type ErrorTrackingRecommendationApiMeta = { [key: string]: unknown }

export interface ErrorTrackingRecommendationApi {
    readonly id: string
    readonly type: string
    readonly meta: ErrorTrackingRecommendationApiMeta
    readonly completed: boolean
    /** @nullable */
    readonly computed_at: string | null
    /** @nullable */
    readonly dismissed_at: string | null
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedErrorTrackingRecommendationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingRecommendationApi[]
}

export interface ErrorTrackingSettingsApi {
    /**
     * Maximum number of exception events ingested per bucket for the entire project. Null removes the limit.
     * @minimum 1
     * @nullable
     */
    project_rate_limit_value?: number | null
    /**
     * Bucket window over which the project-wide rate limit applies, in minutes.
     * @minimum 1
     * @nullable
     */
    project_rate_limit_bucket_size_minutes?: number | null
    /**
     * Maximum number of exception events ingested per bucket for each individual issue. Null removes the limit.
     * @minimum 1
     * @nullable
     */
    per_issue_rate_limit_value?: number | null
    /**
     * Bucket window over which the per-issue rate limit applies, in minutes.
     * @minimum 1
     * @nullable
     */
    per_issue_rate_limit_bucket_size_minutes?: number | null
}

export interface PatchedErrorTrackingSettingsApi {
    /**
     * Maximum number of exception events ingested per bucket for the entire project. Null removes the limit.
     * @minimum 1
     * @nullable
     */
    project_rate_limit_value?: number | null
    /**
     * Bucket window over which the project-wide rate limit applies, in minutes.
     * @minimum 1
     * @nullable
     */
    project_rate_limit_bucket_size_minutes?: number | null
    /**
     * Maximum number of exception events ingested per bucket for each individual issue. Null removes the limit.
     * @minimum 1
     * @nullable
     */
    per_issue_rate_limit_value?: number | null
    /**
     * Bucket window over which the per-issue rate limit applies, in minutes.
     * @minimum 1
     * @nullable
     */
    per_issue_rate_limit_bucket_size_minutes?: number | null
}

export interface ErrorTrackingSpikeDetectionConfigApi {
    /**
     * Time to wait before alerting again for the same issue after a spike is detected.
     * @minimum 1
     */
    snooze_duration_minutes: number
    /**
     * The factor by which the current exception count must exceed the baseline to be considered a spike.
     * @minimum 1
     */
    multiplier: number
    /**
     * The minimum number of exceptions required in a 5-minute window before a spike can be detected.
     * @minimum 1
     */
    threshold: number
}

export interface PatchedErrorTrackingSpikeDetectionConfigApi {
    /**
     * Time to wait before alerting again for the same issue after a spike is detected.
     * @minimum 1
     */
    snooze_duration_minutes?: number
    /**
     * The factor by which the current exception count must exceed the baseline to be considered a spike.
     * @minimum 1
     */
    multiplier?: number
    /**
     * The minimum number of exceptions required in a 5-minute window before a spike can be detected.
     * @minimum 1
     */
    threshold?: number
}

export interface ErrorTrackingSpikeEventIssueApi {
    readonly id: string
    /** @nullable */
    readonly name: string | null
    /** @nullable */
    readonly description: string | null
}

export interface ErrorTrackingSpikeEventApi {
    readonly id: string
    readonly issue: ErrorTrackingSpikeEventIssueApi
    readonly detected_at: string
    readonly computed_baseline: number
    readonly current_bucket_value: number
}

export interface PaginatedErrorTrackingSpikeEventListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingSpikeEventApi[]
}

export interface ErrorTrackingReleaseApi {
    readonly id: string
    hash_id: string
    readonly team_id: number
    readonly created_at: string
    metadata?: unknown
    version: string
    project: string
}

export interface ErrorTrackingStackFrameApi {
    readonly id: string
    /** Raw frame ID in 'hash/part' format */
    readonly raw_id: string
    readonly created_at: string
    contents: unknown
    resolved: boolean
    context?: unknown
    symbol_set_ref?: string
    readonly release: ErrorTrackingReleaseApi
}

export interface PaginatedErrorTrackingStackFrameListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingStackFrameApi[]
}

export interface ErrorTrackingSuppressionRuleApi {
    readonly id: string
    filters: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key: number
    disabled_data?: unknown
    sampling_rate?: number
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedErrorTrackingSuppressionRuleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingSuppressionRuleApi[]
}

export interface ErrorTrackingSuppressionRuleCreateRequestApi {
    /** Optional property-group filters that define which incoming error events should be suppressed. Omit this field or provide an empty `values` array to create a match-all suppression rule. */
    filters?: PropertyGroupFilterValueApi
    /**
     * Fraction of matching events to suppress. Use `1.0` to suppress all matching events.
     * @minimum 0
     * @maximum 1
     */
    sampling_rate?: number
}

export interface PatchedErrorTrackingSuppressionRuleApi {
    readonly id?: string
    filters?: unknown
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order_key?: number
    disabled_data?: unknown
    sampling_rate?: number
    readonly created_at?: string
    readonly updated_at?: string
}

export interface PaginatedErrorTrackingReleaseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingReleaseApi[]
}

export interface PatchedErrorTrackingReleaseApi {
    readonly id?: string
    hash_id?: string
    readonly team_id?: number
    readonly created_at?: string
    metadata?: unknown
    version?: string
    project?: string
}

/**
 * Release associated with this symbol set, if any.
 * @nullable
 */
export type ErrorTrackingSymbolSetApiRelease = { [key: string]: unknown } | null

export interface ErrorTrackingSymbolSetApi {
    /** Unique symbol set ID. */
    readonly id: string
    /** Reference used to match stack frames to this symbol set. */
    readonly ref: string
    /** Project/team ID that owns this symbol set. */
    readonly team_id: number
    /** When this symbol set row was created. */
    readonly created_at: string
    /**
     * When this symbol set was last used to resolve a stack frame.
     * @nullable
     */
    readonly last_used: string | null
    /**
     * Reason symbol lookup failed, if the source map is missing or invalid.
     * @nullable
     */
    readonly failure_reason: string | null
    /** Whether this symbol set has an uploaded source map file available to download. */
    readonly has_uploaded_file: boolean
    /**
     * Release associated with this symbol set, if any.
     * @nullable
     */
    readonly release: ErrorTrackingSymbolSetApiRelease
}

export interface PaginatedErrorTrackingSymbolSetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ErrorTrackingSymbolSetApi[]
}

export interface _SymbolSetDownloadResponseApi {
    /** Presigned URL to download the source map file. Use immediately; expires after one hour. */
    url: string
}

export interface ErrorTrackingSymbolSetFinishUploadApi {
    /** Hash of the uploaded symbol set content. */
    content_hash: string
}

export interface ErrorTrackingSymbolSetBulkDeleteApi {
    /** Symbol set IDs to delete. */
    ids: string[]
}

/**
 * Map of symbol set ID to uploaded content hash.
 */
export type ErrorTrackingSymbolSetBulkFinishUploadApiContentHashes = { [key: string]: string }

export interface ErrorTrackingSymbolSetBulkFinishUploadApi {
    /** Map of symbol set ID to uploaded content hash. */
    content_hashes: ErrorTrackingSymbolSetBulkFinishUploadApiContentHashes
}

export interface ErrorTrackingSymbolSetUploadApi {
    /** Symbol set reference to upload. */
    chunk_id: string
    /**
     * Optional error tracking release ID associated with this symbol set.
     * @nullable
     */
    release_id?: string | null
    /**
     * Optional hash of the symbol set content, used to skip unchanged uploads.
     * @nullable
     */
    content_hash?: string | null
}

export interface ErrorTrackingSymbolSetBulkStartUploadApi {
    /** Legacy list of symbol set references to upload, all associated with `release_id`. */
    chunk_ids?: string[]
    /**
     * Optional error tracking release ID used with `chunk_ids`.
     * @nullable
     */
    release_id?: string | null
    /** Symbol sets to upload with per-symbol release IDs and content hashes. */
    symbol_sets?: ErrorTrackingSymbolSetUploadApi[]
    /** Whether to overwrite uploaded symbol sets whose content hash changed. */
    force?: boolean
}

export type ErrorTrackingAssignmentRulesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingExternalReferencesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingFingerprintsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingGitProviderFileLinksResolveGithubRetrieveParams = {
    /**
     * Code snippet to search for in repository files.
     * @minLength 1
     */
    code_sample: string
    /**
     * File name to match in search results.
     * @minLength 1
     */
    file_name: string
    /**
     * Repository owner or namespace.
     * @minLength 1
     */
    owner: string
    /**
     * Repository name.
     * @minLength 1
     */
    repository: string
}

export type ErrorTrackingGitProviderFileLinksResolveGitlabRetrieveParams = {
    /**
     * Code snippet to search for in repository files.
     * @minLength 1
     */
    code_sample: string
    /**
     * File name to match in search results.
     * @minLength 1
     */
    file_name: string
    /**
     * Repository owner or namespace.
     * @minLength 1
     */
    owner: string
    /**
     * Repository name.
     * @minLength 1
     */
    repository: string
}

export type ErrorTrackingIssuesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingRecommendationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingSpikeEventsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingStackFramesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingSuppressionRulesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingReleasesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingSymbolSetsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
 * Sort order for symbol sets. Prefix with `-` for descending order.

* `created_at` - created_at
* `-created_at` - -created_at
* `ref` - ref
* `-ref` - -ref
* `last_used` - last_used
* `-last_used` - -last_used
 * @minLength 1
 */
    order_by?: string
    /**
     * Exact symbol set reference to filter by.
     * @minLength 1
     */
    ref?: string
    /**
 * Upload status filter: `valid` has an uploaded file, `invalid` is missing a file, `all` returns both.

* `all` - all
* `valid` - valid
* `invalid` - invalid
 * @minLength 1
 */
    status?: ErrorTrackingSymbolSetsListStatus
}

export type ErrorTrackingSymbolSetsListStatus =
    (typeof ErrorTrackingSymbolSetsListStatus)[keyof typeof ErrorTrackingSymbolSetsListStatus]

export const ErrorTrackingSymbolSetsListStatus = {
    All: 'all',
    Valid: 'valid',
    Invalid: 'invalid',
} as const
