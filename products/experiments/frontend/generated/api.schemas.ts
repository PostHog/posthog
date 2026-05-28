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

export interface ExperimentVariantApi {
    /** Variant key. Exactly one variant in feature_flag_variants must use key 'control' (lowercase, exactly) — that is the baseline used for analysis and the special key the experiment runtime expects. Other variants use keys like 'test', 'variant_a', 'variant_b'. Map natural-language names ('original', 'A', 'baseline') to 'control'. */
    key: string
    /** Human-readable variant name. */
    name?: string | null
    rollout_percentage?: number | null
    /** Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided. */
    split_percent?: number | null
}

export interface ExperimentParametersApi {
    /** Experiment variants. If specified, must include a variant with key 'control' (lowercase). Defaults to a 50/50 control/test split when omitted. Minimum 2, maximum 20. */
    feature_flag_variants?: ExperimentVariantApi[] | null
    /** Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments. */
    minimum_detectable_effect?: number | null
    /** Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100. */
    rollout_percentage?: number | null
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

export interface ExperimentApiExposureConfigApi {
    /** Custom exposure event name. */
    event: string
    kind?: 'ExperimentEventExposureConfig'
    /** Event property filters. Pass an empty array if no filters needed. */
    properties: EventPropertyFilterApi[]
}

export interface ExperimentApiExposureCriteriaApi {
    exposure_config?: ExperimentApiExposureConfigApi | null
    filterTestAccounts?: boolean | null
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

export type ExperimentStatusEnumApi = (typeof ExperimentStatusEnumApi)[keyof typeof ExperimentStatusEnumApi]

export const ExperimentStatusEnumApi = {
    Draft: 'draft',
    Running: 'running',
    Paused: 'paused',
    Stopped: 'stopped',
} as const

export type ExperimentApiFeatureFlag = { [key: string]: unknown }

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
     * @maxLength 3000
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible. */
    feature_flag_key: string
    readonly feature_flag: ExperimentApiFeatureFlag
    readonly holdout: ExperimentHoldoutApi
    /**
     * ID of a holdout group to exclude from the experiment.
     * @nullable
     */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort: number | null
    /** Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power. */
    parameters?: ExperimentParametersApi | null
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

  * `web` - web
  * `product` - product */
    type?: ExperimentTypeEnumApi | null
    /** Exposure configuration including filter test accounts and custom exposure events. */
    exposure_criteria?: ExperimentApiExposureCriteriaApi | null
    /** Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project. */
    metrics?: _ExperimentApiMetricsListApi | null
    /** Secondary metrics for additional measurements. Same format as primary metrics. */
    metrics_secondary?: _ExperimentApiMetricsListApi | null
    stats_config?: unknown
    scheduling_config?: unknown
    /** Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it). */
    allow_unknown_events?: boolean
    _create_in_folder?: string
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.

  * `won` - won
  * `lost` - lost
  * `inconclusive` - inconclusive
  * `stopped_early` - stopped_early
  * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @nullable
     */
    conclusion_comment?: string | null
    primary_metrics_ordered_uuids?: unknown
    secondary_metrics_ordered_uuids?: unknown
    only_count_matured_users?: boolean
    /** When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts. */
    update_feature_flag_params?: boolean
    /** Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'stopped' (ended). */
    readonly status: ExperimentStatusEnumApi
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

export type PatchedExperimentApiFeatureFlag = { [key: string]: unknown }

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
     * @maxLength 3000
     * @nullable
     */
    description?: string | null
    /** @nullable */
    start_date?: string | null
    /** @nullable */
    end_date?: string | null
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible. */
    feature_flag_key?: string
    readonly feature_flag?: PatchedExperimentApiFeatureFlag
    readonly holdout?: ExperimentHoldoutApi
    /**
     * ID of a holdout group to exclude from the experiment.
     * @nullable
     */
    holdout_id?: number | null
    /** @nullable */
    readonly exposure_cohort?: number | null
    /** Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power. */
    parameters?: ExperimentParametersApi | null
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

  * `web` - web
  * `product` - product */
    type?: ExperimentTypeEnumApi | null
    /** Exposure configuration including filter test accounts and custom exposure events. */
    exposure_criteria?: ExperimentApiExposureCriteriaApi | null
    /** Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project. */
    metrics?: _ExperimentApiMetricsListApi | null
    /** Secondary metrics for additional measurements. Same format as primary metrics. */
    metrics_secondary?: _ExperimentApiMetricsListApi | null
    stats_config?: unknown
    scheduling_config?: unknown
    /** Suppresses the validation that rejects metrics referencing events not yet ingested by this project. REQUIRES explicit user confirmation before being set to true — never flip this silently to retry a failed call. The default validation catches typo'd event names and missing instrumentation. Set this to true only when the user has confirmed the event is intentional (e.g. they are about to instrument it). */
    allow_unknown_events?: boolean
    _create_in_folder?: string
    /** Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.

  * `won` - won
  * `lost` - lost
  * `inconclusive` - inconclusive
  * `stopped_early` - stopped_early
  * `invalid` - invalid */
    conclusion?: ConclusionEnumApi | null
    /**
     * Comment about the experiment conclusion.
     * @nullable
     */
    conclusion_comment?: string | null
    primary_metrics_ordered_uuids?: unknown
    secondary_metrics_ordered_uuids?: unknown
    only_count_matured_users?: boolean
    /** When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts. */
    update_feature_flag_params?: boolean
    /** Experiment lifecycle state: 'draft' (not yet launched), 'running' (launched with active feature flag), 'paused' (running with feature flag deactivated — virtual state derived from feature_flag.active, not stored), 'stopped' (ended). */
    readonly status?: ExperimentStatusEnumApi
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
    conclusion?: ConclusionEnumApi | null
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
    conclusion?: ConclusionEnumApi | null
    /**
     * Optional comment about the experiment conclusion.
     * @nullable
     */
    conclusion_comment?: string | null
    /** The key of the variant to ship. */
    variant_key: string
    /** If true, prepend a release condition to the feature flag that rolls the variant out to 100% of users, overriding any existing release conditions on the flag. If false (default), only update the variant distribution — existing release conditions are preserved and the variant is served only to users who already match them. */
    release_to_everyone?: boolean
}

/**
 * * `cost` - cost
 * `latency` - latency
 * `eval_pass_rate` - eval_pass_rate
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
     * Filter by archived state. Defaults to non-archived experiments only.
     */
    archived?: boolean
    /**
     * Filter to experiments created by the given user ID.
     */
    created_by_id?: number
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
     * Filter by experiment status. "running" and "paused" are mutually exclusive: "running" returns launched experiments with an active feature flag, "paused" returns launched experiments whose feature flag is deactivated. "complete" is an alias for "stopped". "all" disables status filtering.
     */
    status?: ExperimentsListStatus
}

export type ExperimentsListStatus = (typeof ExperimentsListStatus)[keyof typeof ExperimentsListStatus]

export const ExperimentsListStatus = {
    All: 'all',
    Complete: 'complete',
    Draft: 'draft',
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
