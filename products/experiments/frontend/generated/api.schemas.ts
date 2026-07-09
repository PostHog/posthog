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

/**
 * A holdout group — a stable slice of users excluded from experiment exposure.
 */
export interface ExperimentHoldoutApi {
    readonly id: number
    /**
     * Human-readable name for the holdout group.
     * @maxLength 400
     */
    name: string
    /**
     * Optional description of what this holdout reserves and why.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the **exclusion** percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout. */
    filters?: FeatureFlagConditionGroupSchemaApi[]
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedExperimentHoldoutListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExperimentHoldoutApi[]
}

/**
 * A holdout group — a stable slice of users excluded from experiment exposure.
 */
export interface PatchedExperimentHoldoutApi {
    readonly id?: number
    /**
     * Human-readable name for the holdout group.
     * @maxLength 400
     */
    name?: string
    /**
     * Optional description of what this holdout reserves and why.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** Non-empty list of release-condition groups defining the held-out population, using the same shape as feature-flag release conditions. Each element's `rollout_percentage` (0–100, may be fractional) is the **exclusion** percentage — the share of users held back from all experiments that reference this holdout. `properties` optionally narrows the group by person/group properties. Do not set `variant`: the server normalizes it to `holdout-{id}`. Note that only the first element's `rollout_percentage` is embedded into each linked experiment's feature flag, and this population is shared across every experiment using the holdout. */
    filters?: FeatureFlagConditionGroupSchemaApi[]
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

/**
 * Mixin for serializers to add user access control fields
 */
export interface ExperimentSavedMetricApi {
    readonly id: number
    /**
     * Name of the shared metric. Must be unique within the project (case-insensitive).
     * @maxLength 400
     */
    name: string
    /**
     * Short description of what the metric measures.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics. */
    query: unknown
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    tags?: unknown[]
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedExperimentSavedMetricListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExperimentSavedMetricApi[]
}

/**
 * Mixin for serializers to add user access control fields
 */
export interface PatchedExperimentSavedMetricApi {
    readonly id?: number
    /**
     * Name of the shared metric. Must be unique within the project (case-insensitive).
     * @maxLength 400
     */
    name?: string
    /**
     * Short description of what the metric measures.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** ExperimentMetric JSON. Must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Legacy kinds (ExperimentTrendsQuery, ExperimentFunnelsQuery) are rejected for new shared metrics. */
    query?: unknown
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
    tags?: unknown[]
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

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

export interface ExperimentVariantApi {
    /** Variant key. Exactly one variant in feature_flag_variants must use key 'control' (lowercase, exactly) — that is the baseline used for analysis and the special key the experiment runtime expects. Other variants use keys like 'test', 'variant_a', 'variant_b'. Map natural-language names ('original', 'A', 'baseline') to 'control'. */
    key: string
    /** Human-readable variant name. */
    name?: string | null
    rollout_percentage?: number | null
    /** Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided. */
    split_percent?: number | null
}

/**
 * Free-text notes per variant, keyed by variant key. Use to document what each variant does or its reroute URL.
 */
export type ExperimentParametersApiVariantNotes = { [key: string]: string } | null

export interface ExperimentParametersApi {
    /** Experiment variants. If specified, must include a variant with key 'control' (lowercase). Defaults to a 50/50 control/test split when omitted. Minimum 2, maximum 20. */
    feature_flag_variants?: ExperimentVariantApi[] | null
    /** Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments. */
    minimum_detectable_effect?: number | null
    /** Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100. */
    rollout_percentage?: number | null
    /** Free-text notes per variant, keyed by variant key. Use to document what each variant does or its reroute URL. */
    variant_notes?: ExperimentParametersApiVariantNotes
}

export type ConversionRateInputTypeApi = (typeof ConversionRateInputTypeApi)[keyof typeof ConversionRateInputTypeApi]

export const ConversionRateInputTypeApi = {
    Manual: 'manual',
    Automatic: 'automatic',
} as const

export type ManualMetricTypeApi = (typeof ManualMetricTypeApi)[keyof typeof ManualMetricTypeApi]

export const ManualMetricTypeApi = {
    Funnel: 'funnel',
    MeanCount: 'mean_count',
    MeanSumOrAvg: 'mean_sum_or_avg',
} as const

export interface ExperimentExposureEstimateConfigApi {
    /** 'manual' when the baseline value and exposure rate were entered by hand, 'automatic' when derived from live experiment data. */
    conversionRateInputType: ConversionRateInputTypeApi
    /** Manually entered baseline metric value (a conversion percentage for funnel metrics). Only used in manual mode. */
    manualBaselineValue?: number | null
    /** Manually entered estimate of users exposed to the experiment per day. Only used in manual mode. */
    manualExposureRate?: number | null
    /** Metric type the manual baseline value refers to. Only used in manual mode. */
    manualMetricType?: ManualMetricTypeApi | null
}

export interface ExperimentRunningTimeCalculationApi {
    /** How the exposure estimate is configured: manual user-entered values or automatic from live experiment data. */
    exposure_estimate_config?: ExperimentExposureEstimateConfigApi | null
    /** Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. */
    minimum_detectable_effect?: number | null
    /** Estimated number of days needed to reach the recommended sample size. */
    recommended_running_time?: number | null
    /** Recommended number of exposed users needed for statistical significance. */
    recommended_sample_size?: number | null
}

/**
 * * `web` - web
 * * `product` - product
 */
export type ExperimentTypeEnumApi = (typeof ExperimentTypeEnumApi)[keyof typeof ExperimentTypeEnumApi]

export const ExperimentTypeEnumApi = {
    Web: 'web',
    Product: 'product',
} as const

/**
 * * `won` - won
 * * `lost` - lost
 * * `inconclusive` - inconclusive
 * * `stopped_early` - stopped_early
 * * `invalid` - invalid
 */
export type ConclusionEnumApi = (typeof ConclusionEnumApi)[keyof typeof ConclusionEnumApi]

export const ConclusionEnumApi = {
    Won: 'won',
    Lost: 'lost',
    Inconclusive: 'inconclusive',
    StoppedEarly: 'stopped_early',
    Invalid: 'invalid',
} as const

export type ExperimentStatusEnumApi = (typeof ExperimentStatusEnumApi)[keyof typeof ExperimentStatusEnumApi]

export const ExperimentStatusEnumApi = {
    Draft: 'draft',
    Running: 'running',
    Paused: 'paused',
    ExposureFrozen: 'exposure_frozen',
    Stopped: 'stopped',
} as const

/**
 * Lightweight, read-only serializer for the experiment list endpoint.
 *
 * The list view (and the MCP list tool) render only the scalar and feature-flag fields
 * shared via ``ExperimentBaseSerializer`` — never the metric definitions. Omitting
 * ``metrics``/``metrics_secondary``/``saved_metrics`` lets the list query defer the large
 * JSON columns and skip the saved-metric prefetch plus per-row fingerprinting; that work
 * belongs to the detail response served by ``ExperimentSerializer``.
 *
 * Because the metric fields, the write-side machinery, and the action-name-refreshing
 * ``to_representation`` all live on ``ExperimentSerializer`` rather than the shared base,
 * this serializer needs no overrides: it gets DRF's default ``get_fields`` (no write-only
 * ``holdout_id`` to configure), default ``to_representation`` (no metrics to normalize), and
 * a plain ``ListSerializer`` that never touches the deferred columns. See
 * ``EnterpriseExperimentsViewSet.safely_get_queryset``.
 */
export interface ExperimentBasicApi {
    readonly id: number
    /**
     * Name of the experiment.
     * @maxLength 400
     */
    name: string
    /**
     * Description of the experiment hypothesis and expected outcomes.
     * @maxLength 3000
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible. */
    feature_flag_key: string
    readonly feature_flag: MinimalFeatureFlagApi
    readonly holdout: ExperimentHoldoutApi
    /** @nullable */
    readonly exposure_cohort: number | null
    /** Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config keys (`feature_flag_variants`, `rollout_percentage`) are a deprecated input surface kept for compatibility — the linked feature flag is the source of truth, and reads project its current config into this field. Excluded variants live on the top-level `excluded_variants` field, not here. */
    parameters?: ExperimentParametersApi | null
    /** Running-time calculator state: `minimum_detectable_effect`, `recommended_running_time`, `recommended_sample_size`, and `exposure_estimate_config`. Canonical home for these keys, which historically lived in `parameters`. */
    running_time_calculation?: ExperimentRunningTimeCalculationApi | null
    /**
     * Variant keys to exclude from metric result calculations. Excluded variants are still served to users but omitted from statistical analysis. The baseline variant and holdout pseudo-variants cannot be excluded. Canonical home for what historically lived in `parameters.excluded_variants`.
     * @nullable
     */
    excluded_variants?: string[] | null
    /** Whether the experiment is archived. */
    archived?: boolean
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** Experiment type: web for frontend UI changes, product for backend/API changes.
     *
     * * `web` - web
     * * `product` - product */
    type?: ExperimentTypeEnumApi | null
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.
     *
     * * `won` - won
     * * `lost` - lost
     * * `inconclusive` - inconclusive
     * * `stopped_early` - stopped_early
     * * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @maxLength 4000
     * @nullable
     */
    conclusion_comment?: string | null
    /** Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the already-exposed cohort while metrics keep flowing — virtual state derived from the flag's release groups, not stored), 'stopped' (ended). */
    readonly status: ExperimentStatusEnumApi
    /** Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support them, such as duplicate and copy-to-project. */
    readonly is_legacy: boolean
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedExperimentBasicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExperimentBasicApi[]
}

/**
 * A single release-condition group carrying only the overall rollout percentage, the one
 * groups entry the experiment input applies.
 */
export interface ExperimentFlagRolloutGroupApi {
    /**
     * Percentage of users who enter the experiment (0-100).
     * @minimum 0
     * @maximum 100
     * @nullable
     */
    rollout_percentage?: number | null
    /**
     * Must be empty or omitted: release-condition properties are not supported via the experiment input. Edit the feature flag directly for targeting.
     * @maxItems 0
     */
    properties?: unknown[]
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
export type ExperimentFeatureFlagFiltersApiPayloads = { [key: string]: string }

/**
 * Feature-flag filters accepted by the experiment endpoints: the flag's own filters shape,
 * minus the keys experiments don't apply.
 */
export interface ExperimentFeatureFlagFiltersApi {
    /** Overall rollout as a single group: [{"properties": [], "rollout_percentage": N}]. */
    groups?: ExperimentFlagRolloutGroupApi[]
    /** Multivariate configuration for variant-based rollouts. */
    multivariate?: FeatureFlagMultivariateSchemaApi | null
    /**
     * Group type index for group-based feature flags.
     * @nullable
     */
    aggregation_group_type_index?: number | null
    /** Optional payload values keyed by variant key. */
    payloads?: ExperimentFeatureFlagFiltersApiPayloads
}

/**
 * Flag config for experiment create/update, sent through the linked feature flag's own shape.
 */
export interface ExperimentFeatureFlagInputApi {
    /** Flag config to apply: `multivariate.variants` (exactly one variant key must be the literal string 'control'), `groups` (a single group with `rollout_percentage` only; release conditions are not supported here, edit the feature flag directly), `aggregation_group_type_index`, and `payloads` (JSON-encoded strings keyed by variant key). On update, config this object omits is preserved from the linked flag's current state. */
    filters?: ExperimentFeatureFlagFiltersApi
    /**
     * Whether the flag persists variant assignment across authentication steps.
     * @nullable
     */
    ensure_experience_continuity?: boolean | null
}

export interface ExperimentToSavedMetricApi {
    readonly id: number
    experiment: number
    saved_metric: number
    metadata?: unknown
    readonly created_at: string
    readonly query: unknown
    readonly name: string
}

export type Kind1Api = (typeof Kind1Api)[keyof typeof Kind1Api]

export const Kind1Api = {
    ExperimentEventExposureConfig: 'ExperimentEventExposureConfig',
    ActionsNode: 'ActionsNode',
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

export interface PersonMetadataPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    /** Top-level columns on the persons table (e.g. created_at), not properties JSON */
    type?: 'person_metadata'
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

export interface MetricPropertyFilterApi {
    key: string
    label?: string | null
    operator: PropertyOperatorApi
    type?: 'metric_attribute'
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

export interface ExperimentApiExposureConfigApi {
    /** Custom exposure event name. Required when kind is 'ExperimentEventExposureConfig'. */
    event?: string | null
    /** Action ID. Required when kind is 'ActionsNode'. */
    id?: number | null
    /** Defaults to 'ExperimentEventExposureConfig' when omitted. Pass 'ActionsNode' for an action-based exposure. */
    kind?: Kind1Api | null
    /** Property filters (event, person, and other supported types). Pass an empty array if no filters needed. */
    properties: (
        | EventPropertyFilterApi
        | PersonPropertyFilterApi
        | PersonMetadataPropertyFilterApi
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
        | MetricPropertyFilterApi
        | SpanPropertyFilterApi
        | RevenueAnalyticsPropertyFilterApi
        | WorkflowVariablePropertyFilterApi
    )[]
}

export type MultipleVariantHandlingApi = (typeof MultipleVariantHandlingApi)[keyof typeof MultipleVariantHandlingApi]

export const MultipleVariantHandlingApi = {
    Exclude: 'exclude',
    FirstSeen: 'first_seen',
} as const

export interface ExperimentApiExposureCriteriaApi {
    exposure_config?: ExperimentApiExposureConfigApi | null
    filterTestAccounts?: boolean | null
    /** How to handle entities exposed to multiple variants. 'exclude' (default) drops them from the analysis; 'first_seen' assigns them to the variant from their earliest exposure. */
    multiple_variant_handling?: MultipleVariantHandlingApi | null
}

export type KindApi = (typeof KindApi)[keyof typeof KindApi]

export const KindApi = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type ExperimentMetricMathTypeApi = (typeof ExperimentMetricMathTypeApi)[keyof typeof ExperimentMetricMathTypeApi]

export const ExperimentMetricMathTypeApi = {
    Total: 'total',
    Sum: 'sum',
    UniqueSession: 'unique_session',
    Min: 'min',
    Max: 'max',
    Avg: 'avg',
    Dau: 'dau',
    UniqueGroup: 'unique_group',
    Hogql: 'hogql',
} as const

export type MathGroupTypeIndexApi = (typeof MathGroupTypeIndexApi)[keyof typeof MathGroupTypeIndexApi]

export const MathGroupTypeIndexApi = {
    Number0: 0,
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number4: 4,
} as const

export interface ExperimentApiEventSourceApi {
    /** Event name, e.g. '$pageview'. Required for EventsNode. */
    event?: string | null
    /** Action ID. Required for ActionsNode. */
    id?: number | null
    kind: KindApi
    /** How to aggregate this source. Defaults to 'total' (event count). Use 'sum' together with math_property to aggregate a numeric property — e.g. a ratio numerator of revenue per order. Other options: 'avg', 'min', 'max', 'unique_session', 'dau', 'unique_group', 'hogql'. */
    math?: ExperimentMetricMathTypeApi | null
    /** Group type index to aggregate over. Required when math is 'unique_group'. */
    math_group_type_index?: MathGroupTypeIndexApi | null
    /** HogQL aggregation expression. Required when math is 'hogql' — without it the metric silently falls back to a plain count/sum. */
    math_hogql?: string | null
    /** Numeric event property to aggregate when math is 'sum', 'avg', 'min', or 'max' (e.g. 'revenue'). */
    math_property?: string | null
    /** Event property filters to narrow which events are counted. */
    properties?: EventPropertyFilterApi[] | null
}

export interface ExperimentMetricOutlierHandlingApi {
    ignore_zeros?: boolean | null
    /** Winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). */
    lower_bound_percentile?: number | null
    /** Winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). */
    upper_bound_percentile?: number | null
}

export type ExperimentMetricGoalApi = (typeof ExperimentMetricGoalApi)[keyof typeof ExperimentMetricGoalApi]

export const ExperimentMetricGoalApi = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

export type ExperimentMetricTypeApi = (typeof ExperimentMetricTypeApi)[keyof typeof ExperimentMetricTypeApi]

export const ExperimentMetricTypeApi = {
    Funnel: 'funnel',
    Mean: 'mean',
    Ratio: 'ratio',
    Retention: 'retention',
} as const

export type FunnelConversionWindowTimeUnitApi =
    (typeof FunnelConversionWindowTimeUnitApi)[keyof typeof FunnelConversionWindowTimeUnitApi]

export const FunnelConversionWindowTimeUnitApi = {
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

export type StartHandlingApi = (typeof StartHandlingApi)[keyof typeof StartHandlingApi]

export const StartHandlingApi = {
    FirstSeen: 'first_seen',
    LastSeen: 'last_seen',
} as const

export interface ExperimentApiMetricApi {
    /** For retention metrics: completion event. */
    completion_event?: ExperimentApiEventSourceApi | null
    /** Conversion window duration. */
    conversion_window?: number | null
    /** For ratio metrics: denominator source. */
    denominator?: ExperimentApiEventSourceApi | null
    /** For ratio metrics: winsorization applied to the denominator aggregate. Leave unset for a binomial-style denominator, which is never clamped. */
    denominator_outlier_handling?: ExperimentMetricOutlierHandlingApi | null
    /** Whether higher or lower values indicate success. */
    goal?: ExperimentMetricGoalApi | null
    /** For mean metrics: exclude zero values when computing the winsorization percentile thresholds. */
    ignore_zeros?: boolean | null
    kind?: 'ExperimentMetric'
    /** For mean metrics: winsorization lower percentile bound, as a fraction in [0, 1] (e.g. 0.01 for the 1st percentile). Per-user values below this percentile are clamped to it before aggregation. */
    lower_bound_percentile?: number | null
    metric_type: ExperimentMetricTypeApi
    /** Human-readable metric name. */
    name?: string | null
    /** For ratio metrics: numerator source. */
    numerator?: ExperimentApiEventSourceApi | null
    /** For ratio metrics: winsorization applied to the numerator aggregate, independently of the denominator and each with its own percentile thresholds. */
    numerator_outlier_handling?: ExperimentMetricOutlierHandlingApi | null
    retention_window_end?: number | null
    retention_window_start?: number | null
    retention_window_unit?: FunnelConversionWindowTimeUnitApi | null
    /** For funnel metrics: array of EventsNode/ActionsNode steps. */
    series?: ExperimentApiEventSourceApi[] | null
    /** For mean metrics: event source. */
    source?: ExperimentApiEventSourceApi | null
    /** For retention metrics: start event. */
    start_event?: ExperimentApiEventSourceApi | null
    start_handling?: StartHandlingApi | null
    /** For mean metrics: when set, reports the percentage of users whose per-user summed/counted value reaches or exceeds this threshold. Only meaningful for sum/count math types. */
    threshold?: number | null
    /** For mean metrics: winsorization upper percentile bound, as a fraction in [0, 1] (e.g. 0.99 for the 99th percentile). Per-user values above this percentile are clamped to it before aggregation. */
    upper_bound_percentile?: number | null
    /** Unique identifier. Auto-generated if omitted. */
    uuid?: string | null
}

/**
 * List wrapper for OpenAPI schema generation — the field stores an array of metrics.
 */
export type _ExperimentApiMetricsListApi = ExperimentApiMetricApi[]

/**
 * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
 */
export interface ExperimentWriteApi {
    readonly id: number
    /**
     * Name of the experiment.
     * @maxLength 400
     */
    name: string
    /**
     * Description of the experiment hypothesis and expected outcomes.
     * @maxLength 3000
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible. */
    feature_flag_key: string
    /** Feature-flag config for the experiment, in the flag's own filters shape. The linked flag is the source of truth for variants, rollout, aggregation, payloads, and experience continuity: send config here instead of the deprecated `parameters` keys. On a running experiment, also send `update_feature_flag_params=true`. Cannot be combined with the key of a pre-existing feature flag on create (the experiment links to it as-is). */
    feature_flag?: ExperimentFeatureFlagInputApi
    readonly holdout: ExperimentHoldoutApi
    /**
     * ID of a holdout group to exclude from the experiment.
     * @nullable
     */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort: number | null
    /** Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config keys (`feature_flag_variants`, `rollout_percentage`) are a deprecated input surface kept for compatibility — the linked feature flag is the source of truth, and reads project its current config into this field. Excluded variants live on the top-level `excluded_variants` field, not here. */
    parameters?: ExperimentParametersApi | null
    /** Running-time calculator state: `minimum_detectable_effect`, `recommended_running_time`, `recommended_sample_size`, and `exposure_estimate_config`. Canonical home for these keys, which historically lived in `parameters`. */
    running_time_calculation?: ExperimentRunningTimeCalculationApi | null
    /**
     * Variant keys to exclude from metric result calculations. Excluded variants are still served to users but omitted from statistical analysis. The baseline variant and holdout pseudo-variants cannot be excluded. Canonical home for what historically lived in `parameters.excluded_variants`.
     * @nullable
     */
    excluded_variants?: string[] | null
    secondary_metrics?: unknown
    readonly saved_metrics: readonly ExperimentToSavedMetricApi[]
    /**
     * IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary).
     * @nullable
     */
    saved_metrics_ids?: unknown[] | null
    filters?: unknown
    /** Whether the experiment is archived. */
    archived?: boolean
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** Experiment type: web for frontend UI changes, product for backend/API changes.
     *
     * * `web` - web
     * * `product` - product */
    type?: ExperimentTypeEnumApi | null
    /** Exposure configuration including filter test accounts and custom exposure events. */
    exposure_criteria?: ExperimentApiExposureCriteriaApi | null
    /** Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the read-data-schema tool with query kind 'events' to find available events in the project. */
    metrics?: _ExperimentApiMetricsListApi | null
    /** Secondary metrics for additional measurements. Same format as primary metrics. */
    metrics_secondary?: _ExperimentApiMetricsListApi | null
    stats_config?: unknown
    scheduling_config?: unknown
    /** Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it). */
    allow_unknown_events?: boolean
    _create_in_folder?: string
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.
     *
     * * `won` - won
     * * `lost` - lost
     * * `inconclusive` - inconclusive
     * * `stopped_early` - stopped_early
     * * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @maxLength 4000
     * @nullable
     */
    conclusion_comment?: string | null
    primary_metrics_ordered_uuids?: unknown
    secondary_metrics_ordered_uuids?: unknown
    only_count_matured_users?: boolean
    /** When true, sync the flag config sent in this request (via the `feature_flag` object, or the deprecated `parameters` keys) to the linked feature flag. Draft experiments always sync regardless. On a running experiment, `feature_flag` config without this flag is rejected. */
    update_feature_flag_params?: boolean
    /** Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the already-exposed cohort while metrics keep flowing — virtual state derived from the flag's release groups, not stored), 'stopped' (ended). */
    readonly status: ExperimentStatusEnumApi
    /** Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support them, such as duplicate and copy-to-project. */
    readonly is_legacy: boolean
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

/**
 * Full experiment representation for the detail, create, and update endpoints.
 *
 * Extends the shared read-side fields in ``ExperimentBaseSerializer`` with the metric
 * definitions (``metrics``/``metrics_secondary``/``saved_metrics``) and the write-side
 * fields, and refreshes stale action names while serializing. The list endpoint uses the
 * leaner ``ExperimentBasicSerializer`` instead.
 */
export interface ExperimentApi {
    readonly id: number
    /**
     * Name of the experiment.
     * @maxLength 400
     */
    name: string
    /**
     * Description of the experiment hypothesis and expected outcomes.
     * @maxLength 3000
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible. */
    feature_flag_key: string
    readonly feature_flag: MinimalFeatureFlagApi
    readonly holdout: ExperimentHoldoutApi
    /**
     * ID of a holdout group to exclude from the experiment.
     * @nullable
     */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort: number | null
    /** Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config keys (`feature_flag_variants`, `rollout_percentage`) are a deprecated input surface kept for compatibility — the linked feature flag is the source of truth, and reads project its current config into this field. Excluded variants live on the top-level `excluded_variants` field, not here. */
    parameters?: ExperimentParametersApi | null
    /** Running-time calculator state: `minimum_detectable_effect`, `recommended_running_time`, `recommended_sample_size`, and `exposure_estimate_config`. Canonical home for these keys, which historically lived in `parameters`. */
    running_time_calculation?: ExperimentRunningTimeCalculationApi | null
    /**
     * Variant keys to exclude from metric result calculations. Excluded variants are still served to users but omitted from statistical analysis. The baseline variant and holdout pseudo-variants cannot be excluded. Canonical home for what historically lived in `parameters.excluded_variants`.
     * @nullable
     */
    excluded_variants?: string[] | null
    secondary_metrics?: unknown
    readonly saved_metrics: readonly ExperimentToSavedMetricApi[]
    /**
     * IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary).
     * @nullable
     */
    saved_metrics_ids?: unknown[] | null
    filters?: unknown
    /** Whether the experiment is archived. */
    archived?: boolean
    /** @nullable */
    deleted?: boolean | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** Experiment type: web for frontend UI changes, product for backend/API changes.
     *
     * * `web` - web
     * * `product` - product */
    type?: ExperimentTypeEnumApi | null
    /** Exposure configuration including filter test accounts and custom exposure events. */
    exposure_criteria?: ExperimentApiExposureCriteriaApi | null
    /** Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the read-data-schema tool with query kind 'events' to find available events in the project. */
    metrics?: _ExperimentApiMetricsListApi | null
    /** Secondary metrics for additional measurements. Same format as primary metrics. */
    metrics_secondary?: _ExperimentApiMetricsListApi | null
    stats_config?: unknown
    scheduling_config?: unknown
    /** Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it). */
    allow_unknown_events?: boolean
    _create_in_folder?: string
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.
     *
     * * `won` - won
     * * `lost` - lost
     * * `inconclusive` - inconclusive
     * * `stopped_early` - stopped_early
     * * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @maxLength 4000
     * @nullable
     */
    conclusion_comment?: string | null
    primary_metrics_ordered_uuids?: unknown
    secondary_metrics_ordered_uuids?: unknown
    only_count_matured_users?: boolean
    /** When true, sync the flag config sent in this request (via the `feature_flag` object, or the deprecated `parameters` keys) to the linked feature flag. Draft experiments always sync regardless. On a running experiment, `feature_flag` config without this flag is rejected. */
    update_feature_flag_params?: boolean
    /** Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the already-exposed cohort while metrics keep flowing — virtual state derived from the flag's release groups, not stored), 'stopped' (ended). */
    readonly status: ExperimentStatusEnumApi
    /** Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support them, such as duplicate and copy-to-project. */
    readonly is_legacy: boolean
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

/**
 * Experiment write payload. Identical to Experiment, plus the writable `feature_flag` config input.
 */
export interface PatchedExperimentWriteApi {
    readonly id?: number
    /**
     * Name of the experiment.
     * @maxLength 400
     */
    name?: string
    /**
     * Description of the experiment hypothesis and expected outcomes.
     * @maxLength 3000
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flag-get-all tool first — reuse an existing flag when possible. */
    feature_flag_key?: string
    /** Feature-flag config for the experiment, in the flag's own filters shape. The linked flag is the source of truth for variants, rollout, aggregation, payloads, and experience continuity: send config here instead of the deprecated `parameters` keys. On a running experiment, also send `update_feature_flag_params=true`. Cannot be combined with the key of a pre-existing feature flag on create (the experiment links to it as-is). */
    feature_flag?: ExperimentFeatureFlagInputApi
    readonly holdout?: ExperimentHoldoutApi
    /**
     * ID of a holdout group to exclude from the experiment.
     * @nullable
     */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort?: number | null
    /** Experiment parameters JSON. Supported keys include `custom_exposure_filter` and `variant_notes` (free-text notes per variant, keyed by variant key). Flag config keys (`feature_flag_variants`, `rollout_percentage`) are a deprecated input surface kept for compatibility — the linked feature flag is the source of truth, and reads project its current config into this field. Excluded variants live on the top-level `excluded_variants` field, not here. */
    parameters?: ExperimentParametersApi | null
    /** Running-time calculator state: `minimum_detectable_effect`, `recommended_running_time`, `recommended_sample_size`, and `exposure_estimate_config`. Canonical home for these keys, which historically lived in `parameters`. */
    running_time_calculation?: ExperimentRunningTimeCalculationApi | null
    /**
     * Variant keys to exclude from metric result calculations. Excluded variants are still served to users but omitted from statistical analysis. The baseline variant and holdout pseudo-variants cannot be excluded. Canonical home for what historically lived in `parameters.excluded_variants`.
     * @nullable
     */
    excluded_variants?: string[] | null
    secondary_metrics?: unknown
    readonly saved_metrics?: readonly ExperimentToSavedMetricApi[]
    /**
     * IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary).
     * @nullable
     */
    saved_metrics_ids?: unknown[] | null
    filters?: unknown
    /** Whether the experiment is archived. */
    archived?: boolean
    /** @nullable */
    deleted?: boolean | null
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
    /** Experiment type: web for frontend UI changes, product for backend/API changes.
     *
     * * `web` - web
     * * `product` - product */
    type?: ExperimentTypeEnumApi | null
    /** Exposure configuration including filter test accounts and custom exposure events. */
    exposure_criteria?: ExperimentApiExposureCriteriaApi | null
    /** Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the read-data-schema tool with query kind 'events' to find available events in the project. */
    metrics?: _ExperimentApiMetricsListApi | null
    /** Secondary metrics for additional measurements. Same format as primary metrics. */
    metrics_secondary?: _ExperimentApiMetricsListApi | null
    stats_config?: unknown
    scheduling_config?: unknown
    /** Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it). */
    allow_unknown_events?: boolean
    _create_in_folder?: string
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.
     *
     * * `won` - won
     * * `lost` - lost
     * * `inconclusive` - inconclusive
     * * `stopped_early` - stopped_early
     * * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @maxLength 4000
     * @nullable
     */
    conclusion_comment?: string | null
    primary_metrics_ordered_uuids?: unknown
    secondary_metrics_ordered_uuids?: unknown
    only_count_matured_users?: boolean
    /** When true, sync the flag config sent in this request (via the `feature_flag` object, or the deprecated `parameters` keys) to the linked feature flag. Draft experiments always sync regardless. On a running experiment, `feature_flag` config without this flag is rejected. */
    update_feature_flag_params?: boolean
    /** Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'exposure_frozen' (running with enrollment frozen to the already-exposed cohort while metrics keep flowing — virtual state derived from the flag's release groups, not stored), 'stopped' (ended). */
    readonly status?: ExperimentStatusEnumApi
    /** Whether the experiment uses any legacy-engine metrics (ExperimentTrendsQuery or ExperimentFunnelsQuery). Used to flag legacy experiments and gate actions that don't support them, such as duplicate and copy-to-project. */
    readonly is_legacy?: boolean
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
}

export interface ArchiveExperimentApi {
    /** When the linked feature flag is still enabled, also disable and archive it along with the experiment. Has no effect if the flag is already disabled (it is archived either way). */
    disable_feature_flag?: boolean
}

export interface CopyExperimentToProjectApi {
    /** The team ID to copy the experiment to. */
    target_team_id: number
    /** Optional feature flag key to use in the destination team. */
    feature_flag_key?: string
    /** Optional name for the copied experiment. */
    name?: string
}

export interface EndExperimentApi {
    /** The conclusion of the experiment.
     *
     * * `won` - won
     * * `lost` - lost
     * * `inconclusive` - inconclusive
     * * `stopped_early` - stopped_early
     * * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Optional comment about the experiment conclusion.
     * @maxLength 4000
     * @nullable
     */
    conclusion_comment?: string | null
    /** When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Requires the requesting user to have access to PostHog Code (403 otherwise). Only acts for allowlisted teams; ignored otherwise. */
    open_cleanup_pr?: boolean
}

/**
 * * `manual` - Manual
 * * `cold_run` - Cold Run
 * * `stale_refresh` - Stale Refresh
 * * `auto_refresh` - Auto Refresh
 * * `config_change` - Config Change
 * * `experiment_launch` - Experiment Launch
 * * `experiment_stop` - Experiment Stop
 * * `experiment_update` - Experiment Update
 */
export type TriggerEnumApi = (typeof TriggerEnumApi)[keyof typeof TriggerEnumApi]

export const TriggerEnumApi = {
    Manual: 'manual',
    ColdRun: 'cold_run',
    StaleRefresh: 'stale_refresh',
    AutoRefresh: 'auto_refresh',
    ConfigChange: 'config_change',
    ExperimentLaunch: 'experiment_launch',
    ExperimentStop: 'experiment_stop',
    ExperimentUpdate: 'experiment_update',
} as const

/**
 * Request body for triggering a metrics recalculation.
 */
export interface RecalculateMetricsRequestApi {
    /** What triggered this recalculation (manual is the default for user-initiated runs)
     *
     * * `manual` - Manual
     * * `cold_run` - Cold Run
     * * `stale_refresh` - Stale Refresh
     * * `auto_refresh` - Auto Refresh
     * * `config_change` - Config Change
     * * `experiment_launch` - Experiment Launch
     * * `experiment_stop` - Experiment Stop
     * * `experiment_update` - Experiment Update */
    trigger?: TriggerEnumApi
}

/**
 * * `pending` - Pending
 * * `in_progress` - In Progress
 * * `completed` - Completed
 * * `failed` - Failed
 */
export type ExperimentMetricsRecalculationStatusEnumApi =
    (typeof ExperimentMetricsRecalculationStatusEnumApi)[keyof typeof ExperimentMetricsRecalculationStatusEnumApi]

export const ExperimentMetricsRecalculationStatusEnumApi = {
    Pending: 'pending',
    InProgress: 'in_progress',
    Completed: 'completed',
    Failed: 'failed',
} as const

/**
 * * `recalculation` - recalculation
 * * `timeseries_fallback` - timeseries_fallback
 */
export type ResultSourceEnumApi = (typeof ResultSourceEnumApi)[keyof typeof ResultSourceEnumApi]

export const ResultSourceEnumApi = {
    Recalculation: 'recalculation',
    TimeseriesFallback: 'timeseries_fallback',
} as const

/**
 * * `pending` - pending
 * * `completed` - completed
 * * `failed` - failed
 */
export type MetricRecalculationResultStatusEnumApi =
    (typeof MetricRecalculationResultStatusEnumApi)[keyof typeof MetricRecalculationResultStatusEnumApi]

export const MetricRecalculationResultStatusEnumApi = {
    Pending: 'pending',
    Completed: 'completed',
    Failed: 'failed',
} as const

/**
 * One metric's recalculated result row, read back from ExperimentMetricResult.
 */
export interface MetricRecalculationResultApi {
    /** UUID of the metric this result belongs to */
    readonly metric_uuid: string
    /** Status of this metric's calculation in the run
     *
     * * `pending` - pending
     * * `completed` - completed
     * * `failed` - failed */
    readonly status: MetricRecalculationResultStatusEnumApi
    /** The computed metric result (ExperimentQueryResponse shape); null when status is pending or failed */
    readonly result: unknown
    /**
     * Error message when status is failed; otherwise null
     * @nullable
     */
    readonly error_message: string | null
}

/**
 * Serializer for metrics recalculation status responses.
 */
export interface ExperimentMetricsRecalculationApi {
    /** Unique identifier for this recalculation job */
    readonly id: string
    /** ID of the experiment being recalculated */
    readonly experiment_id: number
    /** Current status of the recalculation job
     *
     * * `pending` - Pending
     * * `in_progress` - In Progress
     * * `completed` - Completed
     * * `failed` - Failed */
    readonly status: ExperimentMetricsRecalculationStatusEnumApi
    /** Total number of metrics to recalculate */
    readonly total_metrics: number
    /** Number of metrics with a COMPLETED result row in this run (derived, not stored) */
    readonly completed_metrics: number
    /** Number of failed metrics in this run (derived): FAILED result rows plus discovery-step failures that never made it to a result row */
    readonly failed_metrics: number
    /** Map of metric_uuid to error details */
    readonly metric_errors: unknown
    /** What triggered this recalculation
     *
     * * `manual` - Manual
     * * `cold_run` - Cold Run
     * * `stale_refresh` - Stale Refresh
     * * `auto_refresh` - Auto Refresh
     * * `config_change` - Config Change
     * * `experiment_launch` - Experiment Launch
     * * `experiment_stop` - Experiment Stop
     * * `experiment_update` - Experiment Update */
    readonly trigger: TriggerEnumApi
    /** When the job was created */
    readonly created_at: string
    /**
     * When processing started
     * @nullable
     */
    readonly started_at: string | null
    /**
     * When processing completed
     * @nullable
     */
    readonly completed_at: string | null
    /**
     * Upper time bound the metrics in this run were calculated against (the data freshness cutoff). Shared by every metric in the run; null until processing starts
     * @nullable
     */
    readonly query_to: string | null
    /** True if returning an existing job rather than a newly created one */
    readonly is_existing: boolean
    /** Where these results came from: 'recalculation' for a real metrics-recalculation run, 'timeseries_fallback' for a cold-start placeholder built from the latest daily timeseries data.
     *
     * * `recalculation` - recalculation
     * * `timeseries_fallback` - timeseries_fallback */
    readonly result_source: ResultSourceEnumApi
    /** Per-metric results computed by this run, scoped by the run's recalc fingerprint */
    readonly results: readonly MetricRecalculationResultApi[]
    /**
     * Count of metric queries currently running in ClickHouse (bounded by worker-pool concurrency)
     * @nullable
     */
    running_metrics?: number | null
    /**
     * Rows read by the run's metric queries so far, both finished and currently running. Cumulative and roughly monotonic across the run; the primary live progress signal
     * @nullable
     */
    rows_read?: number | null
    /**
     * ClickHouse's total_rows_approx across running queries plus the final read_rows of finished ones. A soft ceiling revised mid-scan, so it can exceed or trail rows_read; treat rows_read as the reliable signal
     * @nullable
     */
    estimated_rows_total?: number | null
    /**
     * Bytes read by the run's metric queries so far, both finished and currently running
     * @nullable
     */
    bytes_read?: number | null
    /**
     * Active CPU time (microseconds) consumed by the run's metric queries so far, both finished and currently running
     * @nullable
     */
    active_cpu_time?: number | null
}

export interface ShipVariantApi {
    /** The conclusion of the experiment.
     *
     * * `won` - won
     * * `lost` - lost
     * * `inconclusive` - inconclusive
     * * `stopped_early` - stopped_early
     * * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Optional comment about the experiment conclusion.
     * @maxLength 4000
     * @nullable
     */
    conclusion_comment?: string | null
    /** When true, open a draft pull request that removes the experiment's feature-flag code from the linked repository. Requires the requesting user to have access to PostHog Code (403 otherwise). Only acts for allowlisted teams; ignored otherwise. */
    open_cleanup_pr?: boolean
    /** The key of the variant to ship. */
    variant_key: string
    /** If true, prepend a release condition to the feature flag that rolls the variant out to 100% of users, overriding any existing release conditions on the flag. If false (default), only update the variant distribution — existing release conditions are preserved and the variant is served only to users who already match them. */
    release_to_everyone?: boolean
}

/**
 * * `funnel` - funnel
 * * `mean_count` - mean_count
 * * `mean_sum_or_avg` - mean_sum_or_avg
 * * `ratio` - ratio
 * * `retention` - retention
 */
export type MetricTypeEnumApi = (typeof MetricTypeEnumApi)[keyof typeof MetricTypeEnumApi]

export const MetricTypeEnumApi = {
    Funnel: 'funnel',
    MeanCount: 'mean_count',
    MeanSumOrAvg: 'mean_sum_or_avg',
    Ratio: 'ratio',
    Retention: 'retention',
} as const

/**
 * Raw control-group statistics the calculator uses to derive a baseline value and variance.
 *
 * Supply this when you want the server to compute the baseline value and (for ratio/retention)
 * the delta-method variance, instead of passing `baseline_value`/`variance` directly.
 */
export interface RunningTimeBaselineStatsApi {
    /**
     * Number of control-group samples (users/units) observed.
     * @minimum 0
     */
    number_of_samples: number
    /** Sum of the metric values across the control group (for funnels, the numerator/conversions). */
    sum: number
    /** Sum of squared metric values. Required for ratio/retention variance. */
    sum_squares?: number
    /**
     * Sum of the denominator values. Required for ratio/retention metrics.
     * @nullable
     */
    denominator_sum?: number | null
    /**
     * Sum of squared denominator values (ratio/retention variance).
     * @nullable
     */
    denominator_sum_squares?: number | null
    /**
     * Sum of numerator×denominator products, used for the delta-method covariance term.
     * @nullable
     */
    numerator_denominator_sum_product?: number | null
    /** Per-step counts for funnel metrics; the last entry is the final-step count. */
    step_counts?: number[]
}

/**
 * Inputs for estimating the recommended sample size and running time of an experiment.
 */
export interface RunningTimeCalculationInputApi {
    /** Metric type to size for. 'funnel' for conversion rates, 'mean_count' for event counts per user, 'mean_sum_or_avg' for summed property values per user, 'ratio' and 'retention' for ratio-style metrics (both require baseline_stats or an explicit variance).
     *
     * * `funnel` - funnel
     * * `mean_count` - mean_count
     * * `mean_sum_or_avg` - mean_sum_or_avg
     * * `ratio` - ratio
     * * `retention` - retention */
    metric_type: MetricTypeEnumApi
    /**
     * Smallest relative change to detect, as a percentage (e.g. 5 means a 5% lift). Must be > 0.
     * @minimum 0
     */
    minimum_detectable_effect: number
    /**
     * Total number of variants including control (default 2).
     * @minimum 2
     */
    number_of_variants?: number
    /**
     * Expected exposures per day. When provided, the response includes the recommended running time.
     * @minimum 0
     * @nullable
     */
    exposure_rate_per_day?: number | null
    /**
     * Baseline metric value: conversion rate as a fraction 0-1 (funnel), average per user (mean), or the ratio (ratio/retention). Provide this or baseline_stats.
     * @nullable
     */
    baseline_value?: number | null
    /**
     * Pre-computed variance for ratio/retention metrics. Provide this or baseline_stats when metric_type is ratio/retention and baseline_value is given directly.
     * @nullable
     */
    variance?: number | null
    /** Raw control-group statistics. When provided, the server derives baseline_value and variance. */
    baseline_stats?: RunningTimeBaselineStatsApi | null
}

/**
 * Estimated sample size and running time for the given inputs.
 */
export interface RunningTimeCalculationResultApi {
    /**
     * Baseline metric value used in the calculation (echoed or derived from stats).
     * @nullable
     */
    baseline_value: number | null
    /**
     * Variance used in the calculation; null for funnel metrics (implicit in p(1-p)).
     * @nullable
     */
    variance: number | null
    /**
     * Total recommended sample size across all variants. Null if inputs are insufficient.
     * @nullable
     */
    recommended_sample_size: number | null
    /**
     * Estimated days to reach the recommended sample size. Null when exposure_rate_per_day is omitted.
     * @nullable
     */
    recommended_running_time_days: number | null
}

/**
 * * `cost` - cost
 * * `latency` - latency
 * * `eval_pass_rate` - eval_pass_rate
 */
export type TemplatesEnumApi = (typeof TemplatesEnumApi)[keyof typeof TemplatesEnumApi]

export const TemplatesEnumApi = {
    Cost: 'cost',
    Latency: 'latency',
    EvalPassRate: 'eval_pass_rate',
} as const

export interface CreateFromPromptInputApi {
    /** The name of the LLM prompt to experiment on. Must already exist for this team. */
    prompt_name: string
    /**
     * Ordered list of prompt version numbers to assign to experiment variants. The first entry is the control variant. Must contain between 2 and 10 distinct versions.
     * @minItems 2
     * @maxItems 10
     * @items.minimum 1
     */
    versions: number[]
    /**
     * One or more metric templates to attach as primary metrics. Each template becomes one metric on the experiment. Allowed values: cost, latency, eval_pass_rate.
     * @minItems 1
     * @maxItems 3
     */
    templates: TemplatesEnumApi[]
    /** Optional experiment name. If omitted, a name is generated from the prompt and versions. */
    name?: string
    /** Optional feature flag key. If omitted, a slug is derived from the experiment name. */
    feature_flag_key?: string
    /** Optional experiment description. */
    description?: string
}

export type ExperimentHoldoutsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ExperimentSavedMetricsListParams = {
    /**
     * Filter to shared metrics whose query references this event name. Matches events used directly in metric queries as well as events behind any actions those metrics reference. Use this for reuse discovery (find a metric by what it measures); distinct from 'search', which matches the metric's own name/description/tags.
     */
    event?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type ExperimentsListParams = {
    /**
     * Filter by archived state. Defaults to non-archived experiments only.
     */
    archived?: boolean
    /**
     * Filter to experiments created by the given user(s). Accepts a single user ID, or a JSON-encoded / comma-separated list of user IDs to match any of them.
     */
    created_by_id?: string
    /**
     * Filter to experiments whose metrics reference this event name. Matches events used directly in metric queries as well as events behind any actions those metrics reference.
     */
    event?: string
    /**
     * Filter to experiments linked to the given feature flag ID.
     */
    feature_flag_id?: number
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Field to order by. Prefix with '-' for descending. Allowlisted fields include name, created_at, updated_at, start_date, end_date, duration, and status.
     */
    order?: string
    /**
     * Filter to experiments created from an LLM prompt with this name. Matches experiments whose parameters.prompt_metadata.name equals the given value.
     */
    prompt_name?: string
    /**
     * Free-text search applied to the experiment name (case-insensitive).
     */
    search?: string
    /**
     * Filter by experiment status. "running", "paused", and "exposure_frozen" are mutually exclusive: "running" returns launched experiments with an active feature flag, "paused" returns launched experiments whose feature flag is deactivated, and "exposure_frozen" returns launched experiments whose exposure was frozen to the already-enrolled cohort while metrics keep flowing. "complete" is an alias for "stopped". "all" disables status filtering.
     */
    status?: ExperimentsListStatus
}

export type ExperimentsListStatus = (typeof ExperimentsListStatus)[keyof typeof ExperimentsListStatus]

export const ExperimentsListStatus = {
    All: 'all',
    Complete: 'complete',
    Draft: 'draft',
    ExposureFrozen: 'exposure_frozen',
    Paused: 'paused',
    Running: 'running',
    Stopped: 'stopped',
} as const

export type ExperimentsTimeseriesResultsRetrieveParams = {
    /**
     * Fingerprint of the metric configuration. Available alongside metric_uuid on each metric in the experiment's metrics array.
     */
    fingerprint: string
    /**
     * UUID of the metric to fetch timeseries for. Available on each metric in the experiment's metrics array.
     */
    metric_uuid: string
}

export type ExperimentsPromptTemplatesRetrieve200Item = {
    key: string
    label: string
    description: string
}
