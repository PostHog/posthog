/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
export interface CopyFlagsRequestApi {
    /** Key of the feature flag to copy */
    feature_flag_key: string
    /** Source project ID to copy the flag from */
    from_project: number
    /**
     * List of target project IDs to copy the flag to
     * @maxItems 50
     */
    target_project_ids: number[]
    /** Whether to also copy scheduled changes for this flag */
    copy_schedule?: boolean
}

export interface CopyFlagsSuccessItemApi {
    /** ID of the created feature flag */
    id: number
    /** Key of the feature flag */
    key: string
    /** Name of the feature flag */
    name: string
    /** Whether the flag is active */
    active: boolean
    /** Team ID the flag was copied to */
    team_id: number
}

export interface CopyFlagsResultApi {
    /** Project ID (present on failure) */
    project_id?: number
    /** Error message (present on failure) */
    error_message?: string
}

export interface CopyFlagsResponseApi {
    /** List of successfully copied flags */
    success: CopyFlagsSuccessItemApi[]
    /** List of failed copy attempts */
    failed: CopyFlagsResultApi[]
}

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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

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

/**
 * * `feature_flags` - feature_flags
 * `experiments` - experiments
 * `surveys` - surveys
 * `early_access_features` - early_access_features
 * `web_experiments` - web_experiments
 * `product_tours` - product_tours
 */
export type FeatureFlagCreationContextEnumApi =
    (typeof FeatureFlagCreationContextEnumApi)[keyof typeof FeatureFlagCreationContextEnumApi]

export const FeatureFlagCreationContextEnumApi = {
    FeatureFlags: 'feature_flags',
    Experiments: 'experiments',
    Surveys: 'surveys',
    EarlyAccessFeatures: 'early_access_features',
    WebExperiments: 'web_experiments',
    ProductTours: 'product_tours',
} as const

/**
 * * `server` - Server
 * `client` - Client
 * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

export const EvaluationRuntimeEnumApi = {
    Server: 'server',
    Client: 'client',
    All: 'all',
} as const

/**
 * * `distinct_id` - User ID (default)
 * `device_id` - Device ID
 */
export type BucketingIdentifierEnumApi = (typeof BucketingIdentifierEnumApi)[keyof typeof BucketingIdentifierEnumApi]

export const BucketingIdentifierEnumApi = {
    DistinctId: 'distinct_id',
    DeviceId: 'device_id',
} as const

export type FeatureFlagApiFilters = { [key: string]: unknown }

export type FeatureFlagApiExperimentSetMetadataItem = { [key: string]: unknown }

export type FeatureFlagApiSurveys = { [key: string]: unknown }

export type FeatureFlagApiFeatures = { [key: string]: unknown }

/**
 * Serializer mixin that handles tags for objects.
 */
export interface FeatureFlagApi {
    readonly id: number
    /** contains the description for the flag (field name `name` is kept for backwards-compatibility) */
    name?: string
    /** @maxLength 400 */
    key: string
    filters?: FeatureFlagApiFilters
    deleted?: boolean
    active?: boolean
    readonly created_by: UserBasicApi
    created_at?: string
    /** @nullable */
    readonly updated_at: string | null
    version?: number
    readonly last_modified_by: UserBasicApi
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    readonly experiment_set: readonly number[]
    readonly experiment_set_metadata: readonly FeatureFlagApiExperimentSetMetadataItem[]
    readonly surveys: FeatureFlagApiSurveys
    readonly features: FeatureFlagApiFeatures
    rollback_conditions?: unknown | null
    /** @nullable */
    performed_rollback?: boolean | null
    readonly can_edit: boolean
    tags?: unknown[]
    evaluation_contexts?: unknown[]
    readonly usage_dashboard: number
    analytics_dashboards?: number[]
    /** @nullable */
    has_enriched_analytics?: boolean | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    /** Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.

* `feature_flags` - feature_flags
* `experiments` - experiments
* `surveys` - surveys
* `early_access_features` - early_access_features
* `web_experiments` - web_experiments
* `product_tours` - product_tours */
    creation_context?: FeatureFlagCreationContextEnumApi
    /** @nullable */
    is_remote_configuration?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    readonly status: string
    /** Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | NullEnumApi | null
    /** Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | NullEnumApi | null
    /**
     * Last time this feature flag was called (from $feature_flag_called events)
     * @nullable
     */
    last_called_at?: string | null
    _create_in_folder?: string
    _should_create_usage_dashboard?: boolean
    /** Check if this feature flag is used in any team's session recording linked flag setting. */
    readonly is_used_in_replay_settings: boolean
}

export interface PaginatedFeatureFlagListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: FeatureFlagApi[]
}

/**
 * * `cohort` - cohort
 * `person` - person
 * `group` - group
 */
export type Type380EnumApi = (typeof Type380EnumApi)[keyof typeof Type380EnumApi]

export const Type380EnumApi = {
    Cohort: 'cohort',
    Person: 'person',
    Group: 'group',
} as const

/**
 * * `exact` - exact
 * `is_not` - is_not
 * `icontains` - icontains
 * `not_icontains` - not_icontains
 * `regex` - regex
 * `not_regex` - not_regex
 * `gt` - gt
 * `gte` - gte
 * `lt` - lt
 * `lte` - lte
 */
export type FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi = {
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
} as const

export interface FeatureFlagFilterPropertyGenericSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Comparison value for the property filter. Supports strings, numbers, booleans, and arrays. */
    value: unknown
    /** Operator used to compare the property value.

* `exact` - exact
* `is_not` - is_not
* `icontains` - icontains
* `not_icontains` - not_icontains
* `regex` - regex
* `not_regex` - not_regex
* `gt` - gt
* `gte` - gte
* `lt` - lt
* `lte` - lte */
    operator: FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
}

/**
 * * `is_set` - is_set
 * `is_not_set` - is_not_set
 */
export type Operator3e6EnumApi = (typeof Operator3e6EnumApi)[keyof typeof Operator3e6EnumApi]

export const Operator3e6EnumApi = {
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
} as const

export interface FeatureFlagFilterPropertyExistsSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Existence operator.

* `is_set` - is_set
* `is_not_set` - is_not_set */
    operator: Operator3e6EnumApi
    /** Optional value. Runtime behavior determines whether this is ignored. */
    value?: unknown
}

/**
 * * `is_date_exact` - is_date_exact
 * `is_date_after` - is_date_after
 * `is_date_before` - is_date_before
 */
export type FeatureFlagFilterPropertyDateSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyDateSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyDateSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyDateSchemaOperatorEnumApi = {
    IsDateExact: 'is_date_exact',
    IsDateAfter: 'is_date_after',
    IsDateBefore: 'is_date_before',
} as const

export interface FeatureFlagFilterPropertyDateSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Date comparison operator.

* `is_date_exact` - is_date_exact
* `is_date_after` - is_date_after
* `is_date_before` - is_date_before */
    operator: FeatureFlagFilterPropertyDateSchemaOperatorEnumApi
    /** Date value in ISO format or relative date expression. */
    value: string
}

/**
 * * `semver_gt` - semver_gt
 * `semver_gte` - semver_gte
 * `semver_lt` - semver_lt
 * `semver_lte` - semver_lte
 * `semver_eq` - semver_eq
 * `semver_neq` - semver_neq
 * `semver_tilde` - semver_tilde
 * `semver_caret` - semver_caret
 * `semver_wildcard` - semver_wildcard
 */
export type FeatureFlagFilterPropertySemverSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertySemverSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertySemverSchemaOperatorEnumApi = {
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
} as const

export interface FeatureFlagFilterPropertySemverSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Semantic version comparison operator.

* `semver_gt` - semver_gt
* `semver_gte` - semver_gte
* `semver_lt` - semver_lt
* `semver_lte` - semver_lte
* `semver_eq` - semver_eq
* `semver_neq` - semver_neq
* `semver_tilde` - semver_tilde
* `semver_caret` - semver_caret
* `semver_wildcard` - semver_wildcard */
    operator: FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
    /** Semantic version string. */
    value: string
}

/**
 * * `icontains_multi` - icontains_multi
 * `not_icontains_multi` - not_icontains_multi
 */
export type FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi = {
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export interface FeatureFlagFilterPropertyMultiContainsSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.

* `cohort` - cohort
* `person` - person
* `group` - group */
    type?: Type380EnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Multi-contains operator.

* `icontains_multi` - icontains_multi
* `not_icontains_multi` - not_icontains_multi */
    operator: FeatureFlagFilterPropertyMultiContainsSchemaOperatorEnumApi
    /** List of strings to evaluate against. */
    value: string[]
}

/**
 * * `cohort` - cohort
 */
export type FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi =
    (typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi)[keyof typeof FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi]

export const FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi = {
    Cohort: 'cohort',
} as const

/**
 * * `in` - in
 * `not_in` - not_in
 */
export type FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi = {
    In: 'in',
    NotIn: 'not_in',
} as const

export interface FeatureFlagFilterPropertyCohortInSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Cohort property type required for in/not_in operators.

* `cohort` - cohort */
    type: FeatureFlagFilterPropertyCohortInSchemaTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Membership operator for cohort properties.

* `in` - in
* `not_in` - not_in */
    operator: FeatureFlagFilterPropertyCohortInSchemaOperatorEnumApi
    /** Cohort comparison value (single or list, depending on usage). */
    value: unknown
}

/**
 * * `flag` - flag
 */
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi =
    (typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi)[keyof typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi]

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi = {
    Flag: 'flag',
} as const

/**
 * * `flag_evaluates_to` - flag_evaluates_to
 */
export type FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi =
    (typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi)[keyof typeof FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi]

export const FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi = {
    FlagEvaluatesTo: 'flag_evaluates_to',
} as const

export interface FeatureFlagFilterPropertyFlagEvaluatesSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Flag property type required for flag dependency checks.

* `flag` - flag */
    type: FeatureFlagFilterPropertyFlagEvaluatesSchemaTypeEnumApi
    /**
     * Resolved cohort name for cohort-type filters.
     * @nullable
     */
    cohort_name?: string | null
    /**
     * Group type index when using group-based filters.
     * @nullable
     */
    group_type_index?: number | null
    /** Operator for feature flag dependency evaluation.

* `flag_evaluates_to` - flag_evaluates_to */
    operator: FeatureFlagFilterPropertyFlagEvaluatesSchemaOperatorEnumApi
    /** Value to compare flag evaluation against. */
    value: unknown
}

export type FeatureFlagFilterPropertySchemaApi =
    | FeatureFlagFilterPropertyGenericSchemaApi
    | FeatureFlagFilterPropertyExistsSchemaApi
    | FeatureFlagFilterPropertyDateSchemaApi
    | FeatureFlagFilterPropertySemverSchemaApi
    | FeatureFlagFilterPropertyMultiContainsSchemaApi
    | FeatureFlagFilterPropertyCohortInSchemaApi
    | FeatureFlagFilterPropertyFlagEvaluatesSchemaApi

export interface FeatureFlagConditionGroupSchemaApi {
    /** Property conditions for this release condition group. */
    properties?: FeatureFlagFilterPropertySchemaApi[]
    /** Rollout percentage for this release condition group. */
    rollout_percentage?: number
    /**
     * Variant key override for multivariate flags.
     * @nullable
     */
    variant?: string | null
    /**
     * Group type index for this condition set. None means person-level aggregation.
     * @nullable
     */
    aggregation_group_type_index?: number | null
}

export interface FeatureFlagMultivariateVariantSchemaApi {
    /** Unique key for this variant. */
    key: string
    /** Human-readable name for this variant. */
    name?: string
    /** Variant rollout percentage. */
    rollout_percentage: number
}

export interface FeatureFlagMultivariateSchemaApi {
    /** Variant definitions for multivariate feature flags. */
    variants: FeatureFlagMultivariateVariantSchemaApi[]
}

/**
 * Optional payload values keyed by variant key.
 */
export type FeatureFlagFiltersSchemaApiPayloads = { [key: string]: string }

export type FeatureFlagFiltersSchemaApiSuperGroupsItem = { [key: string]: unknown }

export interface FeatureFlagFiltersSchemaApi {
    /** Release condition groups for the feature flag. */
    groups?: FeatureFlagConditionGroupSchemaApi[]
    /** Multivariate configuration for variant-based rollouts. */
    multivariate?: FeatureFlagMultivariateSchemaApi | null
    /**
     * Group type index for group-based feature flags.
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Optional payload values keyed by variant key. */
    payloads?: FeatureFlagFiltersSchemaApiPayloads
    /** Additional super condition groups used by experiments. */
    super_groups?: FeatureFlagFiltersSchemaApiSuperGroupsItem[]
    /**
     * Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment/{flag_key}.
     * @nullable
     */
    feature_enrollment?: boolean | null
}

export interface FeatureFlagCreateRequestSchemaApi {
    /** Feature flag key. */
    key?: string
    /** Feature flag description (stored in the `name` field for backwards compatibility). */
    name?: string
    /** Feature flag targeting configuration. */
    filters?: FeatureFlagFiltersSchemaApi
    /** Whether the feature flag is active. */
    active?: boolean
    /** Organizational tags for this feature flag. */
    tags?: string[]
    /** Evaluation contexts that control where this flag evaluates at runtime. */
    evaluation_contexts?: string[]
}

export interface PatchedFeatureFlagPartialUpdateRequestSchemaApi {
    /** Feature flag key. */
    key?: string
    /** Feature flag description (stored in the `name` field for backwards compatibility). */
    name?: string
    /** Feature flag targeting configuration. */
    filters?: FeatureFlagFiltersSchemaApi
    /** Whether the feature flag is active. */
    active?: boolean
    /** Organizational tags for this feature flag. */
    tags?: string[]
    /** Evaluation contexts that control where this flag evaluates at runtime. */
    evaluation_contexts?: string[]
}

export interface ChangeApi {
    readonly type: string
    readonly action: string
    readonly field: string
    readonly before: unknown
    readonly after: unknown
}

export interface MergeApi {
    readonly type: string
    readonly source: unknown
    readonly target: unknown
}

export interface TriggerApi {
    readonly job_type: string
    readonly job_id: string
    readonly payload: unknown
}

export interface DetailApi {
    readonly id: string
    changes?: ChangeApi[]
    merge?: MergeApi
    trigger?: TriggerApi
    readonly name: string
    readonly short_id: string
    readonly type: string
}

/**
 * @nullable
 */
export type ActivityLogEntryApiUser = { [key: string]: unknown } | null | null

export interface ActivityLogEntryApi {
    readonly id: string
    /** @nullable */
    readonly user: ActivityLogEntryApiUser
    readonly activity: string
    readonly scope: string
    readonly item_id: string
    detail?: DetailApi
    readonly created_at: string
}

/**
 * Response shape for paginated activity log endpoints.
 */
export interface ActivityLogPaginatedResponseApi {
    results: ActivityLogEntryApi[]
    /** @nullable */
    next: string | null
    /** @nullable */
    previous: string | null
    total_count: number
}

export interface DependentFlagApi {
    /** Feature flag ID */
    id: number
    /** Feature flag key */
    key: string
    /** Feature flag name */
    name: string
}

export interface FeatureFlagStatusResponseApi {
    /** Flag status: active, stale, deleted, or unknown */
    status: string
    /** Human-readable explanation of the status */
    reason: string
}

export type LocalEvaluationResponseApiGroupTypeMapping = { [key: string]: string }

/**
 * Cohort definitions keyed by cohort ID. Each value is a property group structure with 'type' (OR/AND) and 'values' (array of property groups or property filters).
 */
export type LocalEvaluationResponseApiCohorts = { [key: string]: unknown }

export type MinimalFeatureFlagApiFilters = { [key: string]: unknown }

export interface MinimalFeatureFlagApi {
    readonly id: number
    readonly team_id: number
    name?: string
    /** @maxLength 400 */
    key: string
    filters?: MinimalFeatureFlagApiFilters
    deleted?: boolean
    active?: boolean
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    version?: number | null
    /** Specifies where this feature flag should be evaluated

* `server` - Server
* `client` - Client
* `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | NullEnumApi | null
    /** Identifier used for bucketing users into rollout and variants

* `distinct_id` - User ID (default)
* `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | NullEnumApi | null
    readonly evaluation_contexts: readonly string[]
}

export interface LocalEvaluationResponseApi {
    flags: MinimalFeatureFlagApi[]
    group_type_mapping: LocalEvaluationResponseApiGroupTypeMapping
    /** Cohort definitions keyed by cohort ID. Each value is a property group structure with 'type' (OR/AND) and 'values' (array of property groups or property filters). */
    cohorts: LocalEvaluationResponseApiCohorts
}

export interface MyFlagsResponseApi {
    feature_flag: MinimalFeatureFlagApi
    value: unknown
}

/**
 * The release condition to evaluate
 */
export type UserBlastRadiusRequestApiCondition = { [key: string]: unknown }

export interface UserBlastRadiusRequestApi {
    /** The release condition to evaluate */
    condition: UserBlastRadiusRequestApiCondition
    /**
     * Group type index for group-based flags (null for person-based flags)
     * @nullable
     */
    group_type_index?: number | null
}

export interface UserBlastRadiusResponseApi {
    /** Number of users matching the condition */
    users_affected: number
    /** Total number of users in the project */
    total_users: number
}

/**
 * * `FeatureFlag` - feature flag
 */
export type ModelNameEnumApi = (typeof ModelNameEnumApi)[keyof typeof ModelNameEnumApi]

export const ModelNameEnumApi = {
    FeatureFlag: 'FeatureFlag',
} as const

/**
 * * `daily` - daily
 * `weekly` - weekly
 * `monthly` - monthly
 * `yearly` - yearly
 */
export type RecurrenceIntervalEnumApi = (typeof RecurrenceIntervalEnumApi)[keyof typeof RecurrenceIntervalEnumApi]

export const RecurrenceIntervalEnumApi = {
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
    Yearly: 'yearly',
} as const

export interface ScheduledChangeApi {
    readonly id: number
    readonly team_id: number
    /**
     * The ID of the record to modify (e.g. the feature flag ID).
     * @maxLength 200
     */
    record_id: string
    /** The type of record to modify. Currently only "FeatureFlag" is supported.

* `FeatureFlag` - feature flag */
    model_name: ModelNameEnumApi
    /** The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys). */
    payload: unknown
    /** ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z'). */
    scheduled_at: string
    /** @nullable */
    executed_at?: string | null
    /**
     * Return the safely formatted failure reason instead of raw data.
     * @nullable
     */
    readonly failure_reason: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    /** Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules. */
    is_recurring?: boolean
    /** How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.

* `daily` - daily
* `weekly` - weekly
* `monthly` - monthly
* `yearly` - yearly */
    recurrence_interval?: RecurrenceIntervalEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_executed_at: string | null
    /**
     * Optional ISO 8601 datetime after which a recurring schedule stops executing.
     * @nullable
     */
    end_date?: string | null
}

export interface PaginatedScheduledChangeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ScheduledChangeApi[]
}

export interface PatchedScheduledChangeApi {
    readonly id?: number
    readonly team_id?: number
    /**
     * The ID of the record to modify (e.g. the feature flag ID).
     * @maxLength 200
     */
    record_id?: string
    /** The type of record to modify. Currently only "FeatureFlag" is supported.

* `FeatureFlag` - feature flag */
    model_name?: ModelNameEnumApi
    /** The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys). */
    payload?: unknown
    /** ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z'). */
    scheduled_at?: string
    /** @nullable */
    executed_at?: string | null
    /**
     * Return the safely formatted failure reason instead of raw data.
     * @nullable
     */
    readonly failure_reason?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    /** Whether this schedule repeats. Only the 'update_status' operation supports recurring schedules. */
    is_recurring?: boolean
    /** How often the schedule repeats. Required when is_recurring is true. One of: daily, weekly, monthly, yearly.

* `daily` - daily
* `weekly` - weekly
* `monthly` - monthly
* `yearly` - yearly */
    recurrence_interval?: RecurrenceIntervalEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_executed_at?: string | null
    /**
     * Optional ISO 8601 datetime after which a recurring schedule stops executing.
     * @nullable
     */
    end_date?: string | null
}

export type FeatureFlagsListParams = {
    active?: FeatureFlagsListActive
    /**
     * The User ID which initially created the feature flag.
     */
    created_by_id?: string
    /**
     * Filter feature flags by their evaluation runtime.
     */
    evaluation_runtime?: FeatureFlagsListEvaluationRuntime
    /**
     * JSON-encoded list of feature flag keys to exclude from the results.
     */
    excluded_properties?: string
    /**
     * Filter feature flags by presence of evaluation contexts. 'true' returns only flags with at least one evaluation context, 'false' returns only flags without.
     */
    has_evaluation_contexts?: FeatureFlagsListHasEvaluationContexts
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Search by feature flag key or name. Case insensitive.
     */
    search?: string
    /**
     * JSON-encoded list of tag names to filter feature flags by.
     */
    tags?: string
    type?: FeatureFlagsListType
}

export type FeatureFlagsListActive = (typeof FeatureFlagsListActive)[keyof typeof FeatureFlagsListActive]

export const FeatureFlagsListActive = {
    Stale: 'STALE',
    False: 'false',
    True: 'true',
} as const

export type FeatureFlagsListEvaluationRuntime =
    (typeof FeatureFlagsListEvaluationRuntime)[keyof typeof FeatureFlagsListEvaluationRuntime]

export const FeatureFlagsListEvaluationRuntime = {
    Both: 'both',
    Client: 'client',
    Server: 'server',
} as const

export type FeatureFlagsListHasEvaluationContexts =
    (typeof FeatureFlagsListHasEvaluationContexts)[keyof typeof FeatureFlagsListHasEvaluationContexts]

export const FeatureFlagsListHasEvaluationContexts = {
    False: 'false',
    True: 'true',
} as const

export type FeatureFlagsListType = (typeof FeatureFlagsListType)[keyof typeof FeatureFlagsListType]

export const FeatureFlagsListType = {
    Boolean: 'boolean',
    Experiment: 'experiment',
    Multivariant: 'multivariant',
    RemoteConfig: 'remote_config',
} as const

export type FeatureFlagsActivityRetrieve2Params = {
    /**
     * Number of items per page
     * @minimum 1
     */
    limit?: number
    /**
     * Page number
     * @minimum 1
     */
    page?: number
}

export type FeatureFlagsActivityRetrieveParams = {
    /**
     * Number of items per page
     * @minimum 1
     */
    limit?: number
    /**
     * Page number
     * @minimum 1
     */
    page?: number
}

export type FeatureFlagsEvaluationReasonsRetrieveParams = {
    /**
     * User distinct ID
     * @minLength 1
     */
    distinct_id: string
    /**
     * Groups for feature flag evaluation (JSON object string)
     */
    groups?: string
}

export type FeatureFlagsLocalEvaluationRetrieveParams = {
    /**
     * Include cohorts in response
     * @nullable
     */
    send_cohorts?: boolean | null
}

/**
 * Unspecified response body
 */
export type FeatureFlagsLocalEvaluationRetrieve402 = { [key: string]: unknown }

/**
 * Unspecified response body
 */
export type FeatureFlagsLocalEvaluationRetrieve500 = { [key: string]: unknown }

export type FeatureFlagsMyFlagsRetrieveParams = {
    /**
     * Groups for feature flag evaluation (JSON object string)
     */
    groups?: string
}

export type ScheduledChangesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * Filter by model type. Use "FeatureFlag" to see feature flag schedules.
     */
    model_name?: string
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Filter by the ID of a specific feature flag.
     */
    record_id?: string
}
