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
} | null | null

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
    disabled_data?: unknown | null
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

/**
 * Event properties
 */
export type EventPropertyFilterApiType = (typeof EventPropertyFilterApiType)[keyof typeof EventPropertyFilterApiType]

export const EventPropertyFilterApiType = {
    Event: 'event',
} as const

export interface EventPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator?: PropertyOperatorApi | null
    /** Event properties */
    type?: EventPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

/**
 * Person properties
 */
export type PersonPropertyFilterApiType = (typeof PersonPropertyFilterApiType)[keyof typeof PersonPropertyFilterApiType]

export const PersonPropertyFilterApiType = {
    Person: 'person',
} as const

export interface PersonPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    /** Person properties */
    type?: PersonPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export type ElementPropertyFilterApiType =
    (typeof ElementPropertyFilterApiType)[keyof typeof ElementPropertyFilterApiType]

export const ElementPropertyFilterApiType = {
    Element: 'element',
} as const

export interface ElementPropertyFilterApi {
    key: Key10Api
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: ElementPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type EventMetadataPropertyFilterApiType =
    (typeof EventMetadataPropertyFilterApiType)[keyof typeof EventMetadataPropertyFilterApiType]

export const EventMetadataPropertyFilterApiType = {
    EventMetadata: 'event_metadata',
} as const

export interface EventMetadataPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: EventMetadataPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type SessionPropertyFilterApiType =
    (typeof SessionPropertyFilterApiType)[keyof typeof SessionPropertyFilterApiType]

export const SessionPropertyFilterApiType = {
    Session: 'session',
} as const

export interface SessionPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: SessionPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type CohortPropertyFilterApiKey = (typeof CohortPropertyFilterApiKey)[keyof typeof CohortPropertyFilterApiKey]

export const CohortPropertyFilterApiKey = {
    Id: 'id',
} as const

export type CohortPropertyFilterApiType = (typeof CohortPropertyFilterApiType)[keyof typeof CohortPropertyFilterApiType]

export const CohortPropertyFilterApiType = {
    Cohort: 'cohort',
} as const

export interface CohortPropertyFilterApi {
    /** @nullable */
    cohort_name?: string | null
    key?: CohortPropertyFilterApiKey
    /** @nullable */
    label?: string | null
    operator?: PropertyOperatorApi | null
    type?: CohortPropertyFilterApiType
    value: number
}

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export type RecordingPropertyFilterApiType =
    (typeof RecordingPropertyFilterApiType)[keyof typeof RecordingPropertyFilterApiType]

export const RecordingPropertyFilterApiType = {
    Recording: 'recording',
} as const

export interface RecordingPropertyFilterApi {
    key: DurationTypeApi | string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: RecordingPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type LogEntryPropertyFilterApiType =
    (typeof LogEntryPropertyFilterApiType)[keyof typeof LogEntryPropertyFilterApiType]

export const LogEntryPropertyFilterApiType = {
    LogEntry: 'log_entry',
} as const

export interface LogEntryPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: LogEntryPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type GroupPropertyFilterApiType = (typeof GroupPropertyFilterApiType)[keyof typeof GroupPropertyFilterApiType]

export const GroupPropertyFilterApiType = {
    Group: 'group',
} as const

/**
 * @nullable
 */
export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null | null

export interface GroupPropertyFilterApi {
    /** @nullable */
    group_key_names?: GroupPropertyFilterApiGroupKeyNames
    /** @nullable */
    group_type_index?: number | null
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: GroupPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

/**
 * Event property with "$feature/" prepended
 */
export type FeaturePropertyFilterApiType =
    (typeof FeaturePropertyFilterApiType)[keyof typeof FeaturePropertyFilterApiType]

export const FeaturePropertyFilterApiType = {
    Feature: 'feature',
} as const

export interface FeaturePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    /** Event property with "$feature/" prepended */
    type?: FeaturePropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

/**
 * Only flag_evaluates_to operator is allowed for flag dependencies
 */
export type FlagPropertyFilterApiOperator =
    (typeof FlagPropertyFilterApiOperator)[keyof typeof FlagPropertyFilterApiOperator]

export const FlagPropertyFilterApiOperator = {
    FlagEvaluatesTo: 'flag_evaluates_to',
} as const

/**
 * Feature flag dependency
 */
export type FlagPropertyFilterApiType = (typeof FlagPropertyFilterApiType)[keyof typeof FlagPropertyFilterApiType]

export const FlagPropertyFilterApiType = {
    Flag: 'flag',
} as const

export interface FlagPropertyFilterApi {
    /** The key should be the flag ID */
    key: string
    /** @nullable */
    label?: string | null
    /** Only flag_evaluates_to operator is allowed for flag dependencies */
    operator?: FlagPropertyFilterApiOperator
    /** Feature flag dependency */
    type?: FlagPropertyFilterApiType
    /** The value can be true, false, or a variant name */
    value: boolean | string
}

export type HogQLPropertyFilterApiType = (typeof HogQLPropertyFilterApiType)[keyof typeof HogQLPropertyFilterApiType]

export const HogQLPropertyFilterApiType = {
    Hogql: 'hogql',
} as const

export interface HogQLPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    type?: HogQLPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type EmptyPropertyFilterApiType = (typeof EmptyPropertyFilterApiType)[keyof typeof EmptyPropertyFilterApiType]

export const EmptyPropertyFilterApiType = {
    Empty: 'empty',
} as const

export interface EmptyPropertyFilterApi {
    type?: EmptyPropertyFilterApiType
}

export type DataWarehousePropertyFilterApiType =
    (typeof DataWarehousePropertyFilterApiType)[keyof typeof DataWarehousePropertyFilterApiType]

export const DataWarehousePropertyFilterApiType = {
    DataWarehouse: 'data_warehouse',
} as const

export interface DataWarehousePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: DataWarehousePropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type DataWarehousePersonPropertyFilterApiType =
    (typeof DataWarehousePersonPropertyFilterApiType)[keyof typeof DataWarehousePersonPropertyFilterApiType]

export const DataWarehousePersonPropertyFilterApiType = {
    DataWarehousePersonProperty: 'data_warehouse_person_property',
} as const

export interface DataWarehousePersonPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: DataWarehousePersonPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type ErrorTrackingIssueFilterApiType =
    (typeof ErrorTrackingIssueFilterApiType)[keyof typeof ErrorTrackingIssueFilterApiType]

export const ErrorTrackingIssueFilterApiType = {
    ErrorTrackingIssue: 'error_tracking_issue',
} as const

export interface ErrorTrackingIssueFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: ErrorTrackingIssueFilterApiType
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
    /** @nullable */
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
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type: SpanPropertyFilterTypeApi
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type RevenueAnalyticsPropertyFilterApiType =
    (typeof RevenueAnalyticsPropertyFilterApiType)[keyof typeof RevenueAnalyticsPropertyFilterApiType]

export const RevenueAnalyticsPropertyFilterApiType = {
    RevenueAnalytics: 'revenue_analytics',
} as const

export interface RevenueAnalyticsPropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: RevenueAnalyticsPropertyFilterApiType
    value?: (string | number | boolean)[] | string | number | boolean | null
}

export type WorkflowVariablePropertyFilterApiType =
    (typeof WorkflowVariablePropertyFilterApiType)[keyof typeof WorkflowVariablePropertyFilterApiType]

export const WorkflowVariablePropertyFilterApiType = {
    WorkflowVariable: 'workflow_variable',
} as const

export interface WorkflowVariablePropertyFilterApi {
    key: string
    /** @nullable */
    label?: string | null
    operator: PropertyOperatorApi
    type?: WorkflowVariablePropertyFilterApiType
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
export type TypeDe9EnumApi = (typeof TypeDe9EnumApi)[keyof typeof TypeDe9EnumApi]

export const TypeDe9EnumApi = {
    User: 'user',
    Role: 'role',
} as const

export interface ErrorTrackingAssignmentRuleAssigneeRequestApi {
    /** Assignee type. Use `user` for a user ID or `role` for a role UUID.

* `user` - user
* `role` - role */
    type: TypeDe9EnumApi
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
} | null | null

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
    disabled_data?: unknown | null
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
} | null | null

/**
 * Issue linked to this rule
 * @nullable
 */
export type ErrorTrackingGroupingRuleApiIssue = { [key: string]: string } | null | null

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
    disabled_data?: unknown | null
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
    type: TypeDe9EnumApi
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
} | null | null

/**
 * Issue linked to this rule
 * @nullable
 */
export type PatchedErrorTrackingGroupingRuleApiIssue = { [key: string]: string } | null | null

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
    disabled_data?: unknown | null
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
} | null | null

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
} | null | null

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

export interface ErrorTrackingRecommendationApi {
    readonly id: string
    readonly type: string
    readonly meta: unknown
    /** @nullable */
    readonly computed_at: string | null
    /** @nullable */
    readonly dismissed_at: string | null
    /** @nullable */
    readonly next_refresh_at: string | null
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

export interface ErrorTrackingReleaseApi {
    readonly id: string
    hash_id: string
    readonly team_id: number
    readonly created_at: string
    metadata?: unknown | null
    version: string
    project: string
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
    metadata?: unknown | null
    version?: string
    project?: string
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

export interface ErrorTrackingStackFrameApi {
    readonly id: string
    /** Raw frame ID in 'hash/part' format */
    readonly raw_id: string
    readonly created_at: string
    contents: unknown
    resolved: boolean
    context?: unknown | null
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
    disabled_data?: unknown | null
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
    disabled_data?: unknown | null
    sampling_rate?: number
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Release associated with this symbol set
 * @nullable
 */
export type ErrorTrackingSymbolSetApiRelease = { [key: string]: unknown } | null | null

export interface ErrorTrackingSymbolSetApi {
    readonly id: string
    ref: string
    readonly team_id: number
    readonly created_at: string
    /** @nullable */
    last_used?: string | null
    /** @nullable */
    storage_ptr?: string | null
    /** @nullable */
    failure_reason?: string | null
    /**
     * Release associated with this symbol set
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

/**
 * Release associated with this symbol set
 * @nullable
 */
export type PatchedErrorTrackingSymbolSetApiRelease = { [key: string]: unknown } | null | null

export interface PatchedErrorTrackingSymbolSetApi {
    readonly id?: string
    ref?: string
    readonly team_id?: number
    readonly created_at?: string
    /** @nullable */
    last_used?: string | null
    /** @nullable */
    storage_ptr?: string | null
    /** @nullable */
    failure_reason?: string | null
    /**
     * Release associated with this symbol set
     * @nullable
     */
    readonly release?: PatchedErrorTrackingSymbolSetApiRelease
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

export type ErrorTrackingSymbolSetsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingReleasesList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ErrorTrackingSymbolSetsList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
