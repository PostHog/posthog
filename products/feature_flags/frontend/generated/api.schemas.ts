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
    /** Whether to force the copied flag to be disabled in target projects, ignoring the source flag's enabled status */
    disable_copied_flag?: boolean
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
    /** Warnings for flag dependencies that were dropped because no matching active flag exists in the target project */
    flag_dependency_warnings?: string[]
    /** Warning emitted when the flag was copied but its scheduled changes failed to copy */
    schedule_copy_warning?: string
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

export interface OrganizationFeatureFlagRowApi {
    /** ID of the representative feature flag for this key */
    id: number
    /** Team ID the representative feature flag belongs to */
    team_id: number
    /** Feature flag key, unique within the compared projects */
    key: string
    /** Human-readable name of the representative feature flag */
    name: string
    /** Whether the representative feature flag is enabled */
    active: boolean
    /** Release condition filters of the representative feature flag */
    filters: unknown
}

export interface OrganizationFeatureFlagKeysResponseApi {
    /** Total number of distinct flag keys across the compared projects */
    count: number
    /**
     * URL for the next page of results, or null if none
     * @nullable
     */
    next: string | null
    /**
     * URL for the previous page of results, or null if none
     * @nullable
     */
    previous: string | null
    /** One representative flag per distinct key across the compared projects */
    results: OrganizationFeatureFlagRowApi[]
}

export interface EvaluationContextSuggestionRequestApi {
    /**
     * Name of the evaluation context to hide from (POST) or restore to (DELETE) the flag editor's suggestion list. Case-insensitive and whitespace-trimmed.
     * @maxLength 255
     */
    context_name: string
}

export interface EvaluationContextSuggestionResponseApi {
    /** Whether the suggestion visibility change was applied. */
    success: boolean
    /** Normalized name of the affected evaluation context. */
    name: string
    /** Whether the context is now hidden from the flag editor's suggestion list. */
    hidden_from_suggestions: boolean
}

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

export interface FeatureFlagExperimentSetMetadataApi {
    /** ID of the experiment linked to this flag. */
    id: number
    /** Name of the experiment linked to this flag. */
    name: string
    /** Whether the experiment is currently running (started and not yet stopped). A running experiment blocks deletion of the linked flag. */
    is_running: boolean
}

/**
 * * `feature_flags` - feature_flags
 * * `experiments` - experiments
 * * `surveys` - surveys
 * * `early_access_features` - early_access_features
 * * `web_experiments` - web_experiments
 * * `product_tours` - product_tours
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
 * * `client` - Client
 * * `all` - All
 */
export type EvaluationRuntimeEnumApi = (typeof EvaluationRuntimeEnumApi)[keyof typeof EvaluationRuntimeEnumApi]

export const EvaluationRuntimeEnumApi = {
    Server: 'server',
    Client: 'client',
    All: 'all',
} as const

/**
 * * `distinct_id` - User ID (default)
 * * `device_id` - Device ID
 */
export type BucketingIdentifierEnumApi = (typeof BucketingIdentifierEnumApi)[keyof typeof BucketingIdentifierEnumApi]

export const BucketingIdentifierEnumApi = {
    DistinctId: 'distinct_id',
    DeviceId: 'device_id',
} as const

export type FeatureFlagApiFilters = { [key: string]: unknown }

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
    /** Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`). */
    archived?: boolean
    readonly created_by: UserBasicApi
    created_at?: string
    /** @nullable */
    readonly updated_at: string | null
    version?: number
    readonly last_modified_by: UserBasicApi
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    readonly experiment_set: readonly number[]
    readonly experiment_set_metadata: readonly FeatureFlagExperimentSetMetadataApi[]
    readonly surveys: FeatureFlagApiSurveys
    readonly features: FeatureFlagApiFeatures
    rollback_conditions?: unknown
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
     *
     * * `feature_flags` - feature_flags
     * * `experiments` - experiments
     * * `surveys` - surveys
     * * `early_access_features` - early_access_features
     * * `web_experiments` - web_experiments
     * * `product_tours` - product_tours */
    creation_context?: FeatureFlagCreationContextEnumApi
    /** @nullable */
    is_remote_configuration?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    readonly status: string
    /** Specifies where this feature flag should be evaluated
     *
     * * `server` - Server
     * * `client` - Client
     * * `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | null
    /** Identifier used for bucketing users into rollout and variants
     *
     * * `distinct_id` - User ID (default)
     * * `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | null
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
 * * `person` - person
 * * `group` - group
 */
export type PropertyGroupTypeEnumApi = (typeof PropertyGroupTypeEnumApi)[keyof typeof PropertyGroupTypeEnumApi]

export const PropertyGroupTypeEnumApi = {
    Cohort: 'cohort',
    Person: 'person',
    Group: 'group',
} as const

/**
 * * `exact` - exact
 * * `is_not` - is_not
 * * `icontains` - icontains
 * * `not_icontains` - not_icontains
 * * `regex` - regex
 * * `not_regex` - not_regex
 * * `gt` - gt
 * * `gte` - gte
 * * `lt` - lt
 * * `lte` - lte
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
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
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
     *
     * * `exact` - exact
     * * `is_not` - is_not
     * * `icontains` - icontains
     * * `not_icontains` - not_icontains
     * * `regex` - regex
     * * `not_regex` - not_regex
     * * `gt` - gt
     * * `gte` - gte
     * * `lt` - lt
     * * `lte` - lte */
    operator: FeatureFlagFilterPropertyGenericSchemaOperatorEnumApi
}

/**
 * * `is_set` - is_set
 * * `is_not_set` - is_not_set
 */
export type ExistenceOperatorEnumApi = (typeof ExistenceOperatorEnumApi)[keyof typeof ExistenceOperatorEnumApi]

export const ExistenceOperatorEnumApi = {
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
} as const

export interface FeatureFlagFilterPropertyExistsSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
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
     *
     * * `is_set` - is_set
     * * `is_not_set` - is_not_set */
    operator: ExistenceOperatorEnumApi
    /** Optional value. Runtime behavior determines whether this is ignored. */
    value?: unknown
}

/**
 * * `is_date_exact` - is_date_exact
 * * `is_date_before` - is_date_before
 * * `is_date_after` - is_date_after
 */
export type DateOperatorEnumApi = (typeof DateOperatorEnumApi)[keyof typeof DateOperatorEnumApi]

export const DateOperatorEnumApi = {
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
} as const

export interface FeatureFlagFilterPropertyDateSchemaApi {
    /** Property key used in this feature flag condition. */
    key: string
    /** Property filter type. Common values are 'person' and 'cohort'.
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
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
     *
     * * `is_date_exact` - is_date_exact
     * * `is_date_after` - is_date_after
     * * `is_date_before` - is_date_before */
    operator: DateOperatorEnumApi
    /** Date value in ISO format or relative date expression. */
    value: string
}

/**
 * * `semver_gt` - semver_gt
 * * `semver_gte` - semver_gte
 * * `semver_lt` - semver_lt
 * * `semver_lte` - semver_lte
 * * `semver_eq` - semver_eq
 * * `semver_neq` - semver_neq
 * * `semver_tilde` - semver_tilde
 * * `semver_caret` - semver_caret
 * * `semver_wildcard` - semver_wildcard
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
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
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
     *
     * * `semver_gt` - semver_gt
     * * `semver_gte` - semver_gte
     * * `semver_lt` - semver_lt
     * * `semver_lte` - semver_lte
     * * `semver_eq` - semver_eq
     * * `semver_neq` - semver_neq
     * * `semver_tilde` - semver_tilde
     * * `semver_caret` - semver_caret
     * * `semver_wildcard` - semver_wildcard */
    operator: FeatureFlagFilterPropertySemverSchemaOperatorEnumApi
    /** Semantic version string. */
    value: string
}

/**
 * * `icontains_multi` - icontains_multi
 * * `not_icontains_multi` - not_icontains_multi
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
     *
     * * `cohort` - cohort
     * * `person` - person
     * * `group` - group */
    type?: PropertyGroupTypeEnumApi
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
     *
     * * `icontains_multi` - icontains_multi
     * * `not_icontains_multi` - not_icontains_multi */
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
 * * `not_in` - not_in
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
     *
     * * `cohort` - cohort */
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
     *
     * * `in` - in
     * * `not_in` - not_in */
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
     *
     * * `flag` - flag */
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
     *
     * * `flag_evaluates_to` - flag_evaluates_to */
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
    /**
     * Whether this flag has early access feature enrollment enabled. When true, the flag is evaluated against the person property $feature_enrollment/{flag_key}.
     * @nullable
     */
    feature_enrollment?: boolean | null
    /** When true, condition evaluation stops at the first matching condition set rather than continuing to evaluate subsequent groups. */
    early_exit?: boolean
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
    /** Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`). */
    archived?: boolean
    /** Organizational tags for this feature flag. */
    tags?: string[]
    /** Evaluation contexts that control where this flag evaluates at runtime. */
    evaluation_contexts?: string[]
    /**
     * Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.
     * @nullable
     */
    is_remote_configuration?: boolean | null
    /**
     * Whether to persist a user's flag value across the anonymous-to-identified transition (the 'persist across authentication steps' option). Incompatible with device_id bucketing.
     * @nullable
     */
    ensure_experience_continuity?: boolean | null
    /** Where this flag is allowed to evaluate: 'server' (server-side SDKs only), 'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.
     *
     * * `server` - Server
     * * `client` - Client
     * * `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | null
    /** Identifier used to bucket users into rollout percentages and variants: 'distinct_id' (user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.
     *
     * * `distinct_id` - User ID (default)
     * * `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | null
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
    /** Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`). */
    archived?: boolean
    /** Organizational tags for this feature flag. */
    tags?: string[]
    /** Evaluation contexts that control where this flag evaluates at runtime. */
    evaluation_contexts?: string[]
    /**
     * Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.
     * @nullable
     */
    is_remote_configuration?: boolean | null
    /**
     * Whether to persist a user's flag value across the anonymous-to-identified transition (the 'persist across authentication steps' option). Incompatible with device_id bucketing.
     * @nullable
     */
    ensure_experience_continuity?: boolean | null
    /** Where this flag is allowed to evaluate: 'server' (server-side SDKs only), 'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.
     *
     * * `server` - Server
     * * `client` - Client
     * * `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | null
    /** Identifier used to bucket users into rollout percentages and variants: 'distinct_id' (user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.
     *
     * * `distinct_id` - User ID (default)
     * * `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | null
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
export type ActivityLogEntryApiUser = { [key: string]: unknown } | null

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

export interface FeatureFlagRolloutSummaryApi {
    /** True if the flag is effectively rolled out to everyone, independent of recent evaluation. For boolean flags this means at least one release condition targets 100% with no property filters (or there are no release conditions); for multivariate flags it means a single variant is served to 100% via a fully rolled out release condition. This is the signal for 'fully rolled out' / GA — unlike `status`, which only reflects recent evaluation. */
    effectively_full_rollout: boolean
    /** True if any release condition has property filters, i.e. the flag is conditionally targeted rather than a blanket rollout. When true, `max_rollout_percentage` is a percentage within the targeted segment, not of the whole user base. */
    has_targeting_conditions: boolean
    /**
     * Highest rollout percentage (0-100) across the flag's release conditions, treating a missing percentage as 100. Null when the flag has no release conditions. Interpret together with `has_targeting_conditions`.
     * @nullable
     */
    max_rollout_percentage: number | null
    /** True if the flag serves multiple variants (has a multivariate variant set). */
    is_multivariate: boolean
}

export interface FeatureFlagStatusResponseApi {
    /** Flag staleness/evaluation status: active, stale, archived, deleted, or unknown. 'active' means the flag was recently evaluated (or has no usage data yet) — it does NOT mean the flag is fully rolled out. Use the `rollout` object to determine rollout completeness. */
    status: string
    /** Human-readable explanation of the status */
    reason: string
    /** Summary of the flag's rollout configuration, for determining whether it is fully rolled out. */
    rollout: FeatureFlagRolloutSummaryApi
}

export interface FeatureFlagTestEvaluationRequestApi {
    /** User distinct ID to test against (mutually exclusive with person_id) */
    distinct_id?: string
    /** Person ID to test against (mutually exclusive with distinct_id) */
    person_id?: string
    /**
     * Optional point-in-time to evaluate the flag against — both flag conditions and person properties are reconstructed as they existed at that timestamp. ISO 8601 with timezone, e.g. ``2026-04-29T15:30:00Z`` or ``2026-04-29T15:30:00+00:00``. Naive timestamps (no timezone) are interpreted as UTC.
     * @nullable
     */
    timestamp?: string | null
    /** Groups for feature flag evaluation (JSON object, defaults to empty dict) */
    groups?: unknown
}

/**
 * Person properties at the time of evaluation (for historical evaluations)
 */
export type FeatureFlagTestEvaluationResponseApiPersonProperties = { [key: string]: unknown }

export interface FeatureFlagConditionPropertyAnalysisApi {
    /** Property key */
    key: string
    /** Comparison operator */
    operator: string
    /** Expected property value */
    value: unknown
    /** Property type (person, group, etc.) */
    type: string
    /** Actual property value from user */
    actual_value: unknown
    /** Whether this property condition matched */
    matched: boolean
    /** Human-readable explanation of the match result */
    explanation: string
}

export interface FeatureFlagConditionAnalysisApi {
    /** Index of this condition in the feature flag */
    index: number
    /** True when this condition was the one that determined the flag's outcome. Use this to find the winning condition — at most one condition per flag is True. */
    matched: boolean
    /** True when every property in this condition evaluated to true, regardless of whether this condition was the eventual winner. */
    properties_matched?: boolean
    /** Human-readable explanation of why this condition matched/didn't match */
    explanation: string
    /** Rollout percentage for this condition (0.0-100.0) */
    rollout_percentage: number
    /** Whether this condition matched properties but was excluded due to rollout */
    rollout_excluded: boolean
    /**
     * Variant associated with this condition
     * @nullable
     */
    variant: string | null
    /** Analysis of each property in this condition */
    properties: FeatureFlagConditionPropertyAnalysisApi[]
}

export interface FeatureFlagTestEvaluationResponseApi {
    /** Feature flag key */
    flag_key: string
    /** The evaluated value of the feature flag (boolean or variant key string) */
    result: unknown
    /** The reason for the evaluation result */
    reason: string
    /**
     * The index of the condition that matched, if applicable
     * @nullable
     */
    condition_index: number | null
    /** Payload associated with the flag result, if any */
    payload: unknown
    /** Person properties at the time of evaluation (for historical evaluations) */
    person_properties: FeatureFlagTestEvaluationResponseApiPersonProperties
    /**
     * The distinct_id used for rollout/variant bucketing. Echoes the caller-provided distinct_id when one was sent; null on the person_id path so the endpoint doesn't leak the person's other distinct_ids to a feature_flag:read-only token.
     * @nullable
     */
    evaluation_distinct_id: string | null
    /** Detailed analysis of each condition in the feature flag */
    conditions: FeatureFlagConditionAnalysisApi[]
}

export interface ErrorResponseApi {
    /** Error message */
    error: string
}

export type FeatureFlagVersionResponseApiFilters = { [key: string]: unknown }

/**
 * Feature flag state at a given version plus reconstruction metadata.
 */
export interface FeatureFlagVersionResponseApi {
    readonly id: number
    /** @maxLength 400 */
    key: string
    name?: string
    readonly filters: FeatureFlagVersionResponseApiFilters
    active?: boolean
    deleted?: boolean
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    version?: number | null
    rollback_conditions?: unknown
    /** @nullable */
    performed_rollback?: boolean | null
    /** @nullable */
    ensure_experience_continuity?: boolean | null
    /** @nullable */
    has_enriched_analytics?: boolean | null
    /** @nullable */
    is_remote_configuration?: boolean | null
    /** @nullable */
    has_encrypted_payloads?: boolean | null
    /** Specifies where this feature flag should be evaluated
     *
     * * `server` - Server
     * * `client` - Client
     * * `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | null
    /** Identifier used for bucketing users into rollout and variants
     *
     * * `distinct_id` - User ID (default)
     * * `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | null
    /**
     * Last time this feature flag was called (from $feature_flag_called events)
     * @nullable
     */
    last_called_at?: string | null
    created_at?: string
    /** @nullable */
    readonly created_by: number | null
    /** False for the current version; true for reconstructed historical versions. */
    readonly is_historical: boolean
    /** @nullable */
    readonly version_timestamp: string | null
    /**
     * User from the activity log entry that produced this version.
     * @nullable
     */
    readonly modified_by: number | null
}

/**
 * * `true` - true
 * * `false` - false
 * * `STALE` - STALE
 */
export type ActiveEnumApi = (typeof ActiveEnumApi)[keyof typeof ActiveEnumApi]

export const ActiveEnumApi = {
    True: 'true',
    False: 'false',
    Stale: 'STALE',
} as const

/**
 * * `boolean` - boolean
 * * `multivariant` - multivariant
 * * `experiment` - experiment
 * * `remote_config` - remote_config
 */
export type BulkDeleteFiltersTypeEnumApi =
    (typeof BulkDeleteFiltersTypeEnumApi)[keyof typeof BulkDeleteFiltersTypeEnumApi]

export const BulkDeleteFiltersTypeEnumApi = {
    Boolean: 'boolean',
    Multivariant: 'multivariant',
    Experiment: 'experiment',
    RemoteConfig: 'remote_config',
} as const

/**
 * Allowed filter keys for bulk_delete — same shape as the list endpoint's query params.
 */
export interface BulkDeleteFiltersApi {
    /** Filter by active state.
     *
     * * `true` - true
     * * `false` - false
     * * `STALE` - STALE */
    active?: ActiveEnumApi
    /** Filter to flags created by a specific user ID. */
    created_by_id?: number
    /** Search by feature flag key or name (case-insensitive). */
    search?: string
    /** Filter by flag type.
     *
     * * `boolean` - boolean
     * * `multivariant` - multivariant
     * * `experiment` - experiment
     * * `remote_config` - remote_config */
    type?: BulkDeleteFiltersTypeEnumApi
    /** Filter by evaluation runtime.
     *
     * * `server` - Server
     * * `client` - Client
     * * `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi
    /** JSON-encoded property filter to exclude. Same shape as the list endpoint. */
    excluded_properties?: string
    /** Tag names to filter by. Flags carrying at least one of these tags match. */
    tags?: string[]
    /** Tag names to exclude. Flags carrying any of these tags are filtered out. */
    excluded_tags?: string[]
    /** When true, only matches flags with at least one evaluation context. */
    has_evaluation_contexts?: boolean
    /** Filter by archived state. When omitted, archived flags are excluded. */
    archived?: boolean
}

export interface BulkDeleteRequestApi {
    /** Filter criteria — same shape as the list endpoint's query params. Mutually exclusive with `ids`. Use this to bulk-delete by search/active/tags/etc. instead of supplying explicit IDs. */
    filters?: BulkDeleteFiltersApi
    /**
     * Explicit feature flag IDs to soft-delete. Mutually exclusive with `filters`.
     * @items.minimum 1
     */
    ids?: number[]
}

/**
 * * `fully_rolled_out` - fully_rolled_out
 * * `not_rolled_out` - not_rolled_out
 * * `partial` - partial
 */
export type RolloutStateEnumApi = (typeof RolloutStateEnumApi)[keyof typeof RolloutStateEnumApi]

export const RolloutStateEnumApi = {
    FullyRolledOut: 'fully_rolled_out',
    NotRolledOut: 'not_rolled_out',
    Partial: 'partial',
} as const

export interface BulkDeleteDeletedItemApi {
    /** ID of the soft-deleted flag. */
    id: number
    /** The flag key at the time of deletion. */
    key: string
    /** Rollout state captured before deletion.
     *
     * * `fully_rolled_out` - fully_rolled_out
     * * `not_rolled_out` - not_rolled_out
     * * `partial` - partial */
    rollout_state: RolloutStateEnumApi
    /**
     * Variant key when a multivariate flag was fully rolled out to a single variant; otherwise null.
     * @nullable
     */
    active_variant: string | null
}

export interface BulkDeleteErrorItemApi {
    /** Feature flag ID — integer for valid inputs; the original raw value for invalid inputs. */
    id: unknown
    /** The flag key, when known. */
    key?: string
    /** Human-readable reason the flag could not be deleted. */
    reason: string
}

/**
 * Schema-only — referenced from ``@extend_schema(responses=...)`` to describe the wire format.
 * Never instantiate this for validation or call ``.is_valid()`` / ``.errors`` on it: the
 * declared ``errors`` field shadows DRF's inherited ``Serializer.errors`` ReturnDict property,
 * so accessing ``serializer.errors`` would return this field descriptor instead of validation
 * errors. The handler builds the response dict directly; this class exists only so drf-spectacular
 * can render the response in the OpenAPI spec and downstream generated clients.
 */
export interface BulkDeleteResponseApi {
    /** Flags successfully soft-deleted. */
    deleted: BulkDeleteDeletedItemApi[]
    /** Flags that could not be deleted, with reasons. */
    errors: BulkDeleteErrorItemApi[]
}

export interface BulkKeysRequestApi {
    /** Feature flag IDs to look up keys for. Strings of digits are also accepted; any other value is reported in the response `warning` field and otherwise ignored. */
    ids?: unknown[]
}

/**
 * Mapping of feature flag ID (as a string) to flag key, for IDs that exist in this project.
 */
export type BulkKeysResponseApiKeys = { [key: string]: string }

export interface BulkKeysResponseApi {
    /** Mapping of feature flag ID (as a string) to flag key, for IDs that exist in this project. */
    keys: BulkKeysResponseApiKeys
    /** Present when some submitted IDs were not numeric and were ignored. */
    warning?: string
}

/**
 * * `add` - add
 * * `remove` - remove
 * * `set` - set
 */
export type BulkUpdateTagsActionEnumApi = (typeof BulkUpdateTagsActionEnumApi)[keyof typeof BulkUpdateTagsActionEnumApi]

export const BulkUpdateTagsActionEnumApi = {
    Add: 'add',
    Remove: 'remove',
    Set: 'set',
} as const

export interface BulkUpdateTagsRequestApi {
    /**
     * List of object IDs to update tags on.
     * @maxItems 500
     */
    ids: number[]
    /** 'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.
     *
     * * `add` - add
     * * `remove` - remove
     * * `set` - set */
    action: BulkUpdateTagsActionEnumApi
    /** Tag names to add, remove, or set. */
    tags: string[]
}

export interface BulkUpdateTagsItemApi {
    id: number
    tags: string[]
}

export interface BulkUpdateTagsErrorApi {
    id: number
    reason: string
}

export interface BulkUpdateTagsResponseApi {
    updated: BulkUpdateTagsItemApi[]
    skipped: BulkUpdateTagsErrorApi[]
}

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
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    version?: number | null
    /** Specifies where this feature flag should be evaluated
     *
     * * `server` - Server
     * * `client` - Client
     * * `all` - All */
    evaluation_runtime?: EvaluationRuntimeEnumApi | BlankEnumApi | null
    /** Identifier used for bucketing users into rollout and variants
     *
     * * `distinct_id` - User ID (default)
     * * `device_id` - Device ID */
    bucketing_identifier?: BucketingIdentifierEnumApi | BlankEnumApi | null
    readonly evaluation_contexts: readonly string[]
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
    /** Number of entities matching the condition (users or groups depending on group_type_index) */
    affected: number
    /** Total number of entities of this type in the project */
    total: number
}

export interface FlagValueItemApi {
    name: unknown
}

export interface FlagValueResponseApi {
    results: FlagValueItemApi[]
    refreshing: boolean
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
 * * `weekly` - weekly
 * * `monthly` - monthly
 * * `yearly` - yearly
 */
export type ScheduledChangeRecurrenceIntervalEnumApi =
    (typeof ScheduledChangeRecurrenceIntervalEnumApi)[keyof typeof ScheduledChangeRecurrenceIntervalEnumApi]

export const ScheduledChangeRecurrenceIntervalEnumApi = {
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
     *
     * * `FeatureFlag` - feature flag */
    model_name: ModelNameEnumApi
    /** The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys). */
    payload: unknown
    /** ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z'). */
    scheduled_at: string
    /** @nullable */
    readonly executed_at: string | null
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
     *
     * * `daily` - daily
     * * `weekly` - weekly
     * * `monthly` - monthly
     * * `yearly` - yearly */
    recurrence_interval?: ScheduledChangeRecurrenceIntervalEnumApi | null
    /**
     * @maxLength 100
     * @nullable
     */
    cron_expression?: string | null
    /** @nullable */
    readonly last_executed_at: string | null
    /**
     * Optional ISO 8601 datetime after which a recurring schedule stops executing.
     * @nullable
     */
    end_date?: string | null
    /** @nullable */
    readonly timezone: string | null
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
     *
     * * `FeatureFlag` - feature flag */
    model_name?: ModelNameEnumApi
    /** The change to apply. Must include an 'operation' key and a 'value' key. Supported operations: 'update_status' (value: true/false to enable/disable the flag), 'add_release_condition' (value: object with 'groups', 'payloads', and 'multivariate' keys), 'update_variants' (value: object with 'variants' and 'payloads' keys). */
    payload?: unknown
    /** ISO 8601 datetime when the change should be applied (e.g. '2025-06-01T14:00:00Z'). */
    scheduled_at?: string
    /** @nullable */
    readonly executed_at?: string | null
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
     *
     * * `daily` - daily
     * * `weekly` - weekly
     * * `monthly` - monthly
     * * `yearly` - yearly */
    recurrence_interval?: ScheduledChangeRecurrenceIntervalEnumApi | null
    /**
     * @maxLength 100
     * @nullable
     */
    cron_expression?: string | null
    /** @nullable */
    readonly last_executed_at?: string | null
    /**
     * Optional ISO 8601 datetime after which a recurring schedule stops executing.
     * @nullable
     */
    end_date?: string | null
    /** @nullable */
    readonly timezone?: string | null
}

export type OrgFeatureFlagsKeysParams = {
    /**
     * Page size (max 100)
     */
    limit?: number
    /**
     * Pagination offset
     */
    offset?: number
    /**
     * Filter by key or name
     */
    search?: string
    /**
     * Teams to compare, in priority order. Defaults to all accessible teams in the org.
     */
    team_ids?: number[]
}

export type OrganizationsProjectsEvaluationContextSuggestionsDestroyParams = {
    /**
     * Name of the evaluation context to restore to suggestions.
     */
    context_name: string
}

export type EnvironmentsEvaluationContextSuggestionsDestroyParams = {
    /**
     * Name of the evaluation context to restore to suggestions.
     */
    context_name: string
}

export type FeatureFlagsListParams = {
    active?: FeatureFlagsListActive
    /**
     * Filter by archived state. When omitted, archived flags are excluded.
     */
    archived?: FeatureFlagsListArchived
    /**
     * Filter by the user(s) who created the feature flag. Accepts a single user ID, or a JSON-encoded / comma-separated list of user IDs to match any of them.
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
     * JSON-encoded list of tag names to exclude. Flags carrying any of these tags are filtered out.
     */
    excluded_tags?: string
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

export type FeatureFlagsListArchived = (typeof FeatureFlagsListArchived)[keyof typeof FeatureFlagsListArchived]

export const FeatureFlagsListArchived = {
    False: 'false',
    True: 'true',
} as const

export type FeatureFlagsListEvaluationRuntime =
    (typeof FeatureFlagsListEvaluationRuntime)[keyof typeof FeatureFlagsListEvaluationRuntime]

export const FeatureFlagsListEvaluationRuntime = {
    All: 'all',
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

export type FeatureFlagsAllActivityRetrieveParams = {
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

export type FeatureFlagsMyFlagsRetrieveParams = {
    /**
     * Groups for feature flag evaluation (JSON object string)
     */
    groups?: string
}

export type FlagValueValuesRetrieveParams = {
    /**
     * The flag ID
     */
    key?: string
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
