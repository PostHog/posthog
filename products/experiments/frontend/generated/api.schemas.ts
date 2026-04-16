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

export interface ExperimentHoldoutApi {
    readonly id: number
    /** @maxLength 400 */
    name: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    filters?: unknown
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
}

export interface PaginatedExperimentHoldoutListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExperimentHoldoutApi[]
}

export interface PatchedExperimentHoldoutApi {
    readonly id?: number
    /** @maxLength 400 */
    name?: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    filters?: unknown
    readonly created_by?: UserBasicApi
    readonly created_at?: string
    readonly updated_at?: string
}

/**
 * Mixin for serializers to add user access control fields
 */
export interface ExperimentSavedMetricApi {
    readonly id: number
    /** @maxLength 400 */
    name: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
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
    /** @maxLength 400 */
    name?: string
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
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

export interface ExperimentVariantApi {
    /** Variant key, e.g. 'control', 'test', 'variant_a'. */
    key: string
    /**
     * Human-readable variant name.
     * @nullable
     */
    name?: string | null
    /** Percentage of users assigned to this variant (0–100). All variants must sum to 100. */
    rollout_percentage: number
}

export interface ExperimentParametersApi {
    /**
     * Experiment variants. If not specified, defaults to a 50/50 control/test split.
     * @nullable
     */
    feature_flag_variants?: ExperimentVariantApi[] | null
    /**
     * Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.
     * @nullable
     */
    minimum_detectable_effect?: number | null
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

/**
 * * `web` - web
 * `product` - product
 */
export type ExperimentTypeEnumApi = (typeof ExperimentTypeEnumApi)[keyof typeof ExperimentTypeEnumApi]

export const ExperimentTypeEnumApi = {
    Web: 'web',
    Product: 'product',
} as const

export type ExperimentApiExposureConfigApiKind =
    (typeof ExperimentApiExposureConfigApiKind)[keyof typeof ExperimentApiExposureConfigApiKind]

export const ExperimentApiExposureConfigApiKind = {
    ExperimentEventExposureConfig: 'ExperimentEventExposureConfig',
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

export interface ExperimentApiExposureConfigApi {
    /** Custom exposure event name. */
    event: string
    kind?: ExperimentApiExposureConfigApiKind
    /** Event property filters. Pass an empty array if no filters needed. */
    properties: EventPropertyFilterApi[]
}

export interface ExperimentApiExposureCriteriaApi {
    exposure_config?: ExperimentApiExposureConfigApi | null
    /** @nullable */
    filterTestAccounts?: boolean | null
}

export type KindApi = (typeof KindApi)[keyof typeof KindApi]

export const KindApi = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export interface ExperimentApiEventSourceApi {
    /**
     * Event name, e.g. '$pageview'. Required for EventsNode.
     * @nullable
     */
    event?: string | null
    /**
     * Action ID. Required for ActionsNode.
     * @nullable
     */
    id?: number | null
    kind: KindApi
    /**
     * Event property filters to narrow which events are counted.
     * @nullable
     */
    properties?: EventPropertyFilterApi[] | null
}

export type ExperimentMetricGoalApi = (typeof ExperimentMetricGoalApi)[keyof typeof ExperimentMetricGoalApi]

export const ExperimentMetricGoalApi = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

export type ExperimentApiMetricApiKind = (typeof ExperimentApiMetricApiKind)[keyof typeof ExperimentApiMetricApiKind]

export const ExperimentApiMetricApiKind = {
    ExperimentMetric: 'ExperimentMetric',
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
    /**
     * Conversion window duration.
     * @nullable
     */
    conversion_window?: number | null
    /** For ratio metrics: denominator source. */
    denominator?: ExperimentApiEventSourceApi | null
    /** Whether higher or lower values indicate success. */
    goal?: ExperimentMetricGoalApi | null
    kind?: ExperimentApiMetricApiKind
    metric_type: ExperimentMetricTypeApi
    /**
     * Human-readable metric name.
     * @nullable
     */
    name?: string | null
    /** For ratio metrics: numerator source. */
    numerator?: ExperimentApiEventSourceApi | null
    /** @nullable */
    retention_window_end?: number | null
    /** @nullable */
    retention_window_start?: number | null
    retention_window_unit?: FunnelConversionWindowTimeUnitApi | null
    /**
     * For funnel metrics: array of EventsNode/ActionsNode steps.
     * @nullable
     */
    series?: ExperimentApiEventSourceApi[] | null
    /** For mean metrics: event source. */
    source?: ExperimentApiEventSourceApi | null
    /** For retention metrics: start event. */
    start_event?: ExperimentApiEventSourceApi | null
    start_handling?: StartHandlingApi | null
    /**
     * Unique identifier. Auto-generated if omitted.
     * @nullable
     */
    uuid?: string | null
}

/**
 * List wrapper for OpenAPI schema generation — the field stores an array of metrics.
 */
export type _ExperimentApiMetricsListApi = ExperimentApiMetricApi[]

/**
 * * `won` - won
 * `lost` - lost
 * `inconclusive` - inconclusive
 * `stopped_early` - stopped_early
 * `invalid` - invalid
 */
export type ConclusionEnumApi = (typeof ConclusionEnumApi)[keyof typeof ConclusionEnumApi]

export const ConclusionEnumApi = {
    Won: 'won',
    Lost: 'lost',
    Inconclusive: 'inconclusive',
    StoppedEarly: 'stopped_early',
    Invalid: 'invalid',
} as const

/**
 * * `draft` - Draft
 * `running` - Running
 * `stopped` - Stopped
 */
export type ExperimentStatusEnumApi = (typeof ExperimentStatusEnumApi)[keyof typeof ExperimentStatusEnumApi]

export const ExperimentStatusEnumApi = {
    Draft: 'draft',
    Running: 'running',
    Stopped: 'stopped',
} as const

/**
 * Mixin for serializers to add user access control fields
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
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible. */
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
    /** Variant definitions and statistical configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and rollout_percentage; percentages must sum to 100. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power. */
    parameters?: ExperimentParametersApi | null
    secondary_metrics?: unknown | null
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

* `web` - web
* `product` - product */
    type?: ExperimentTypeEnumApi | NullEnumApi | null
    /** Exposure configuration including filter test accounts and custom exposure events. */
    exposure_criteria?: ExperimentApiExposureCriteriaApi | null
    /** Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project. */
    metrics?: _ExperimentApiMetricsListApi | null
    /** Secondary metrics for additional measurements. Same format as primary metrics. */
    metrics_secondary?: _ExperimentApiMetricsListApi | null
    stats_config?: unknown | null
    scheduling_config?: unknown | null
    allow_unknown_events?: boolean
    _create_in_folder?: string
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.

* `won` - won
* `lost` - lost
* `inconclusive` - inconclusive
* `stopped_early` - stopped_early
* `invalid` - invalid */
    conclusion?: ConclusionEnumApi | NullEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @nullable
     */
    conclusion_comment?: string | null
    primary_metrics_ordered_uuids?: unknown | null
    secondary_metrics_ordered_uuids?: unknown | null
    only_count_matured_users?: boolean
    /** When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts. */
    update_feature_flag_params?: boolean
    readonly status: ExperimentStatusEnumApi | NullEnumApi | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedExperimentListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExperimentApi[]
}

/**
 * Mixin for serializers to add user access control fields
 */
export interface PatchedExperimentApi {
    readonly id?: number
    /**
     * Name of the experiment.
     * @maxLength 400
     */
    name?: string
    /**
     * Description of the experiment hypothesis and expected outcomes.
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible. */
    feature_flag_key?: string
    readonly feature_flag?: MinimalFeatureFlagApi
    readonly holdout?: ExperimentHoldoutApi
    /**
     * ID of a holdout group to exclude from the experiment.
     * @nullable
     */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort?: number | null
    /** Variant definitions and statistical configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and rollout_percentage; percentages must sum to 100. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power. */
    parameters?: ExperimentParametersApi | null
    secondary_metrics?: unknown | null
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

* `web` - web
* `product` - product */
    type?: ExperimentTypeEnumApi | NullEnumApi | null
    /** Exposure configuration including filter test accounts and custom exposure events. */
    exposure_criteria?: ExperimentApiExposureCriteriaApi | null
    /** Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project. */
    metrics?: _ExperimentApiMetricsListApi | null
    /** Secondary metrics for additional measurements. Same format as primary metrics. */
    metrics_secondary?: _ExperimentApiMetricsListApi | null
    stats_config?: unknown | null
    scheduling_config?: unknown | null
    allow_unknown_events?: boolean
    _create_in_folder?: string
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.

* `won` - won
* `lost` - lost
* `inconclusive` - inconclusive
* `stopped_early` - stopped_early
* `invalid` - invalid */
    conclusion?: ConclusionEnumApi | NullEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @nullable
     */
    conclusion_comment?: string | null
    primary_metrics_ordered_uuids?: unknown | null
    secondary_metrics_ordered_uuids?: unknown | null
    only_count_matured_users?: boolean
    /** When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts. */
    update_feature_flag_params?: boolean
    readonly status?: ExperimentStatusEnumApi | NullEnumApi | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
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

* `won` - won
* `lost` - lost
* `inconclusive` - inconclusive
* `stopped_early` - stopped_early
* `invalid` - invalid */
    conclusion?: ConclusionEnumApi | NullEnumApi | null
    /**
     * Optional comment about the experiment conclusion.
     * @nullable
     */
    conclusion_comment?: string | null
}

export interface ShipVariantApi {
    /** The conclusion of the experiment.

* `won` - won
* `lost` - lost
* `inconclusive` - inconclusive
* `stopped_early` - stopped_early
* `invalid` - invalid */
    conclusion?: ConclusionEnumApi | NullEnumApi | null
    /**
     * Optional comment about the experiment conclusion.
     * @nullable
     */
    conclusion_comment?: string | null
    /** The key of the variant to ship to 100% of users. */
    variant_key: string
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
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ExperimentsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
