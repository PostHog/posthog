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

/**
 * Must be 'ExperimentMetric'.
 */
export type ExperimentApiMetricsItemKind =
    (typeof ExperimentApiMetricsItemKind)[keyof typeof ExperimentApiMetricsItemKind]

export const ExperimentApiMetricsItemKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

/**
 * Type of metric measurement.
 */
export type ExperimentApiMetricsItemMetricType =
    (typeof ExperimentApiMetricsItemMetricType)[keyof typeof ExperimentApiMetricsItemMetricType]

export const ExperimentApiMetricsItemMetricType = {
    Mean: 'mean',
    Funnel: 'funnel',
    Ratio: 'ratio',
    Retention: 'retention',
} as const

export type ExperimentApiMetricsItemSourceKind =
    (typeof ExperimentApiMetricsItemSourceKind)[keyof typeof ExperimentApiMetricsItemSourceKind]

export const ExperimentApiMetricsItemSourceKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type ExperimentApiMetricsItemSeriesItemKind =
    (typeof ExperimentApiMetricsItemSeriesItemKind)[keyof typeof ExperimentApiMetricsItemSeriesItemKind]

export const ExperimentApiMetricsItemSeriesItemKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type ExperimentApiMetricsItemNumeratorKind =
    (typeof ExperimentApiMetricsItemNumeratorKind)[keyof typeof ExperimentApiMetricsItemNumeratorKind]

export const ExperimentApiMetricsItemNumeratorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type ExperimentApiMetricsItemDenominatorKind =
    (typeof ExperimentApiMetricsItemDenominatorKind)[keyof typeof ExperimentApiMetricsItemDenominatorKind]

export const ExperimentApiMetricsItemDenominatorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * Whether higher or lower values indicate success.
 */
export type ExperimentApiMetricsItemGoal =
    (typeof ExperimentApiMetricsItemGoal)[keyof typeof ExperimentApiMetricsItemGoal]

export const ExperimentApiMetricsItemGoal = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

/**
 * Must be 'ExperimentMetric'.
 */
export type ExperimentApiMetricsSecondaryItemKind =
    (typeof ExperimentApiMetricsSecondaryItemKind)[keyof typeof ExperimentApiMetricsSecondaryItemKind]

export const ExperimentApiMetricsSecondaryItemKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

/**
 * Type of metric measurement.
 */
export type ExperimentApiMetricsSecondaryItemMetricType =
    (typeof ExperimentApiMetricsSecondaryItemMetricType)[keyof typeof ExperimentApiMetricsSecondaryItemMetricType]

export const ExperimentApiMetricsSecondaryItemMetricType = {
    Mean: 'mean',
    Funnel: 'funnel',
    Ratio: 'ratio',
    Retention: 'retention',
} as const

export type ExperimentApiMetricsSecondaryItemSourceKind =
    (typeof ExperimentApiMetricsSecondaryItemSourceKind)[keyof typeof ExperimentApiMetricsSecondaryItemSourceKind]

export const ExperimentApiMetricsSecondaryItemSourceKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type ExperimentApiMetricsSecondaryItemSeriesItemKind =
    (typeof ExperimentApiMetricsSecondaryItemSeriesItemKind)[keyof typeof ExperimentApiMetricsSecondaryItemSeriesItemKind]

export const ExperimentApiMetricsSecondaryItemSeriesItemKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type ExperimentApiMetricsSecondaryItemNumeratorKind =
    (typeof ExperimentApiMetricsSecondaryItemNumeratorKind)[keyof typeof ExperimentApiMetricsSecondaryItemNumeratorKind]

export const ExperimentApiMetricsSecondaryItemNumeratorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type ExperimentApiMetricsSecondaryItemDenominatorKind =
    (typeof ExperimentApiMetricsSecondaryItemDenominatorKind)[keyof typeof ExperimentApiMetricsSecondaryItemDenominatorKind]

export const ExperimentApiMetricsSecondaryItemDenominatorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * Whether higher or lower values indicate success.
 */
export type ExperimentApiMetricsSecondaryItemGoal =
    (typeof ExperimentApiMetricsSecondaryItemGoal)[keyof typeof ExperimentApiMetricsSecondaryItemGoal]

export const ExperimentApiMetricsSecondaryItemGoal = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

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

export type Item = {
    /** Variant key (e.g., 'control', 'variant_a', 'new_design'). */
    key: string
    /** Human-readable variant name. */
    name?: string
    /**
     * Percentage of users to show this variant.
     * @minimum 0
     * @maximum 100
     */
    rollout_percentage: number
}

/**
 * Configuration object containing variant definitions (feature_flag_variants) and minimum detectable effect.
 * @nullable
 */
export type ExperimentApiParameters = {
    /** Experiment variants. If not specified, defaults to 50/50 control/test split. */
    feature_flag_variants?: Item[]
    /** Minimum detectable effect in percentage. Lower values require more users but detect smaller changes. Suggest 20-30%% for most experiments. */
    minimum_detectable_effect?: number
} | null | null

export type ExperimentApiSavedMetricsIdsItem = { [key: string]: unknown }

/**
 * Exposure configuration including filter test accounts and custom exposure events.
 * @nullable
 */
export type ExperimentApiExposureCriteria = {
    /** Whether to filter out internal test accounts. */
    filterTestAccounts?: boolean
    /** Custom exposure event configuration. */
    exposure_config?: {
        kind?: 'ExperimentEventExposureConfig'
        /** Custom exposure event name. */
        event?: string
    }
} | null | null

/**
 * For mean metrics: EventsNode with 'kind' and 'event' fields.
 */
export type ExperimentApiMetricsItemSource = {
    kind?: ExperimentApiMetricsItemSourceKind
    /** Event name, e.g. '$pageview'. */
    event?: string
}

export type ExperimentApiMetricsItemSeriesItem = {
    kind?: ExperimentApiMetricsItemSeriesItemKind
    event?: string
}

/**
 * For ratio metrics: the numerator EventsNode.
 */
export type ExperimentApiMetricsItemNumerator = {
    kind?: ExperimentApiMetricsItemNumeratorKind
    event?: string
}

/**
 * For ratio metrics: the denominator EventsNode.
 */
export type ExperimentApiMetricsItemDenominator = {
    kind?: ExperimentApiMetricsItemDenominatorKind
    event?: string
}

/**
 * Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease').
 */
export type ExperimentApiMetricsItem = {
    /** Must be 'ExperimentMetric'. */
    kind: ExperimentApiMetricsItemKind
    /** Type of metric measurement. */
    metric_type: ExperimentApiMetricsItemMetricType
    /** Human-readable metric name. */
    name?: string
    /** Unique identifier for the metric. Auto-generated if not provided. */
    uuid?: string
    /** For mean metrics: EventsNode with 'kind' and 'event' fields. */
    source?: ExperimentApiMetricsItemSource
    /** For funnel metrics: array of EventsNode/ActionsNode steps. */
    series?: ExperimentApiMetricsItemSeriesItem[]
    /** For ratio metrics: the numerator EventsNode. */
    numerator?: ExperimentApiMetricsItemNumerator
    /** For ratio metrics: the denominator EventsNode. */
    denominator?: ExperimentApiMetricsItemDenominator
    /** Whether higher or lower values indicate success. */
    goal?: ExperimentApiMetricsItemGoal
    /** Conversion window duration. */
    conversion_window?: number
}

/**
 * For mean metrics: EventsNode with 'kind' and 'event' fields.
 */
export type ExperimentApiMetricsSecondaryItemSource = {
    kind?: ExperimentApiMetricsSecondaryItemSourceKind
    /** Event name, e.g. '$pageview'. */
    event?: string
}

export type ExperimentApiMetricsSecondaryItemSeriesItem = {
    kind?: ExperimentApiMetricsSecondaryItemSeriesItemKind
    event?: string
}

/**
 * For ratio metrics: the numerator EventsNode.
 */
export type ExperimentApiMetricsSecondaryItemNumerator = {
    kind?: ExperimentApiMetricsSecondaryItemNumeratorKind
    event?: string
}

/**
 * For ratio metrics: the denominator EventsNode.
 */
export type ExperimentApiMetricsSecondaryItemDenominator = {
    kind?: ExperimentApiMetricsSecondaryItemDenominatorKind
    event?: string
}

/**
 * Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease').
 */
export type ExperimentApiMetricsSecondaryItem = {
    /** Must be 'ExperimentMetric'. */
    kind: ExperimentApiMetricsSecondaryItemKind
    /** Type of metric measurement. */
    metric_type: ExperimentApiMetricsSecondaryItemMetricType
    /** Human-readable metric name. */
    name?: string
    /** Unique identifier for the metric. Auto-generated if not provided. */
    uuid?: string
    /** For mean metrics: EventsNode with 'kind' and 'event' fields. */
    source?: ExperimentApiMetricsSecondaryItemSource
    /** For funnel metrics: array of EventsNode/ActionsNode steps. */
    series?: ExperimentApiMetricsSecondaryItemSeriesItem[]
    /** For ratio metrics: the numerator EventsNode. */
    numerator?: ExperimentApiMetricsSecondaryItemNumerator
    /** For ratio metrics: the denominator EventsNode. */
    denominator?: ExperimentApiMetricsSecondaryItemDenominator
    /** Whether higher or lower values indicate success. */
    goal?: ExperimentApiMetricsSecondaryItemGoal
    /** Conversion window duration. */
    conversion_window?: number
}

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
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. */
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
    /**
     * Configuration object containing variant definitions (feature_flag_variants) and minimum detectable effect.
     * @nullable
     */
    parameters?: ExperimentApiParameters
    secondary_metrics?: unknown | null
    readonly saved_metrics: readonly ExperimentToSavedMetricApi[]
    /**
     * IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary).
     * @nullable
     */
    saved_metrics_ids?: ExperimentApiSavedMetricsIdsItem[] | null
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
    /**
     * Exposure configuration including filter test accounts and custom exposure events.
     * @nullable
     */
    exposure_criteria?: ExperimentApiExposureCriteria
    /**
     * Primary experiment metrics array. Each metric defines what to measure (e.g., mean, funnel, ratio).
     * @nullable
     */
    metrics?: ExperimentApiMetricsItem[] | null
    /**
     * Secondary experiment metrics array for additional measurements.
     * @nullable
     */
    metrics_secondary?: ExperimentApiMetricsSecondaryItem[] | null
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
 * Configuration object containing variant definitions (feature_flag_variants) and minimum detectable effect.
 * @nullable
 */
export type PatchedExperimentApiParameters = {
    /** Experiment variants. If not specified, defaults to 50/50 control/test split. */
    feature_flag_variants?: Item[]
    /** Minimum detectable effect in percentage. Lower values require more users but detect smaller changes. Suggest 20-30%% for most experiments. */
    minimum_detectable_effect?: number
} | null | null

export type PatchedExperimentApiSavedMetricsIdsItem = { [key: string]: unknown }

/**
 * Exposure configuration including filter test accounts and custom exposure events.
 * @nullable
 */
export type PatchedExperimentApiExposureCriteria = {
    /** Whether to filter out internal test accounts. */
    filterTestAccounts?: boolean
    /** Custom exposure event configuration. */
    exposure_config?: {
        kind?: 'ExperimentEventExposureConfig'
        /** Custom exposure event name. */
        event?: string
    }
} | null | null

/**
 * Must be 'ExperimentMetric'.
 */
export type PatchedExperimentApiMetricsItemKind =
    (typeof PatchedExperimentApiMetricsItemKind)[keyof typeof PatchedExperimentApiMetricsItemKind]

export const PatchedExperimentApiMetricsItemKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

/**
 * Type of metric measurement.
 */
export type PatchedExperimentApiMetricsItemMetricType =
    (typeof PatchedExperimentApiMetricsItemMetricType)[keyof typeof PatchedExperimentApiMetricsItemMetricType]

export const PatchedExperimentApiMetricsItemMetricType = {
    Mean: 'mean',
    Funnel: 'funnel',
    Ratio: 'ratio',
    Retention: 'retention',
} as const

export type PatchedExperimentApiMetricsItemSourceKind =
    (typeof PatchedExperimentApiMetricsItemSourceKind)[keyof typeof PatchedExperimentApiMetricsItemSourceKind]

export const PatchedExperimentApiMetricsItemSourceKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * For mean metrics: EventsNode with 'kind' and 'event' fields.
 */
export type PatchedExperimentApiMetricsItemSource = {
    kind?: PatchedExperimentApiMetricsItemSourceKind
    /** Event name, e.g. '$pageview'. */
    event?: string
}

export type PatchedExperimentApiMetricsItemSeriesItemKind =
    (typeof PatchedExperimentApiMetricsItemSeriesItemKind)[keyof typeof PatchedExperimentApiMetricsItemSeriesItemKind]

export const PatchedExperimentApiMetricsItemSeriesItemKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type PatchedExperimentApiMetricsItemSeriesItem = {
    kind?: PatchedExperimentApiMetricsItemSeriesItemKind
    event?: string
}

export type PatchedExperimentApiMetricsItemNumeratorKind =
    (typeof PatchedExperimentApiMetricsItemNumeratorKind)[keyof typeof PatchedExperimentApiMetricsItemNumeratorKind]

export const PatchedExperimentApiMetricsItemNumeratorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * For ratio metrics: the numerator EventsNode.
 */
export type PatchedExperimentApiMetricsItemNumerator = {
    kind?: PatchedExperimentApiMetricsItemNumeratorKind
    event?: string
}

export type PatchedExperimentApiMetricsItemDenominatorKind =
    (typeof PatchedExperimentApiMetricsItemDenominatorKind)[keyof typeof PatchedExperimentApiMetricsItemDenominatorKind]

export const PatchedExperimentApiMetricsItemDenominatorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * For ratio metrics: the denominator EventsNode.
 */
export type PatchedExperimentApiMetricsItemDenominator = {
    kind?: PatchedExperimentApiMetricsItemDenominatorKind
    event?: string
}

/**
 * Whether higher or lower values indicate success.
 */
export type PatchedExperimentApiMetricsItemGoal =
    (typeof PatchedExperimentApiMetricsItemGoal)[keyof typeof PatchedExperimentApiMetricsItemGoal]

export const PatchedExperimentApiMetricsItemGoal = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

/**
 * Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease').
 */
export type PatchedExperimentApiMetricsItem = {
    /** Must be 'ExperimentMetric'. */
    kind: PatchedExperimentApiMetricsItemKind
    /** Type of metric measurement. */
    metric_type: PatchedExperimentApiMetricsItemMetricType
    /** Human-readable metric name. */
    name?: string
    /** Unique identifier for the metric. Auto-generated if not provided. */
    uuid?: string
    /** For mean metrics: EventsNode with 'kind' and 'event' fields. */
    source?: PatchedExperimentApiMetricsItemSource
    /** For funnel metrics: array of EventsNode/ActionsNode steps. */
    series?: PatchedExperimentApiMetricsItemSeriesItem[]
    /** For ratio metrics: the numerator EventsNode. */
    numerator?: PatchedExperimentApiMetricsItemNumerator
    /** For ratio metrics: the denominator EventsNode. */
    denominator?: PatchedExperimentApiMetricsItemDenominator
    /** Whether higher or lower values indicate success. */
    goal?: PatchedExperimentApiMetricsItemGoal
    /** Conversion window duration. */
    conversion_window?: number
}

/**
 * Must be 'ExperimentMetric'.
 */
export type PatchedExperimentApiMetricsSecondaryItemKind =
    (typeof PatchedExperimentApiMetricsSecondaryItemKind)[keyof typeof PatchedExperimentApiMetricsSecondaryItemKind]

export const PatchedExperimentApiMetricsSecondaryItemKind = {
    ExperimentMetric: 'ExperimentMetric',
} as const

/**
 * Type of metric measurement.
 */
export type PatchedExperimentApiMetricsSecondaryItemMetricType =
    (typeof PatchedExperimentApiMetricsSecondaryItemMetricType)[keyof typeof PatchedExperimentApiMetricsSecondaryItemMetricType]

export const PatchedExperimentApiMetricsSecondaryItemMetricType = {
    Mean: 'mean',
    Funnel: 'funnel',
    Ratio: 'ratio',
    Retention: 'retention',
} as const

export type PatchedExperimentApiMetricsSecondaryItemSourceKind =
    (typeof PatchedExperimentApiMetricsSecondaryItemSourceKind)[keyof typeof PatchedExperimentApiMetricsSecondaryItemSourceKind]

export const PatchedExperimentApiMetricsSecondaryItemSourceKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * For mean metrics: EventsNode with 'kind' and 'event' fields.
 */
export type PatchedExperimentApiMetricsSecondaryItemSource = {
    kind?: PatchedExperimentApiMetricsSecondaryItemSourceKind
    /** Event name, e.g. '$pageview'. */
    event?: string
}

export type PatchedExperimentApiMetricsSecondaryItemSeriesItemKind =
    (typeof PatchedExperimentApiMetricsSecondaryItemSeriesItemKind)[keyof typeof PatchedExperimentApiMetricsSecondaryItemSeriesItemKind]

export const PatchedExperimentApiMetricsSecondaryItemSeriesItemKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

export type PatchedExperimentApiMetricsSecondaryItemSeriesItem = {
    kind?: PatchedExperimentApiMetricsSecondaryItemSeriesItemKind
    event?: string
}

export type PatchedExperimentApiMetricsSecondaryItemNumeratorKind =
    (typeof PatchedExperimentApiMetricsSecondaryItemNumeratorKind)[keyof typeof PatchedExperimentApiMetricsSecondaryItemNumeratorKind]

export const PatchedExperimentApiMetricsSecondaryItemNumeratorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * For ratio metrics: the numerator EventsNode.
 */
export type PatchedExperimentApiMetricsSecondaryItemNumerator = {
    kind?: PatchedExperimentApiMetricsSecondaryItemNumeratorKind
    event?: string
}

export type PatchedExperimentApiMetricsSecondaryItemDenominatorKind =
    (typeof PatchedExperimentApiMetricsSecondaryItemDenominatorKind)[keyof typeof PatchedExperimentApiMetricsSecondaryItemDenominatorKind]

export const PatchedExperimentApiMetricsSecondaryItemDenominatorKind = {
    EventsNode: 'EventsNode',
    ActionsNode: 'ActionsNode',
} as const

/**
 * For ratio metrics: the denominator EventsNode.
 */
export type PatchedExperimentApiMetricsSecondaryItemDenominator = {
    kind?: PatchedExperimentApiMetricsSecondaryItemDenominatorKind
    event?: string
}

/**
 * Whether higher or lower values indicate success.
 */
export type PatchedExperimentApiMetricsSecondaryItemGoal =
    (typeof PatchedExperimentApiMetricsSecondaryItemGoal)[keyof typeof PatchedExperimentApiMetricsSecondaryItemGoal]

export const PatchedExperimentApiMetricsSecondaryItemGoal = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

/**
 * Experiment metric. Set kind to 'ExperimentMetric' and metric_type to one of: 'mean' (requires source with EventsNode), 'funnel' (requires series array of EventsNode/ActionsNode steps), 'ratio' (requires numerator and denominator EventsNode). Optional fields: name, uuid, conversion_window, goal ('increase' or 'decrease').
 */
export type PatchedExperimentApiMetricsSecondaryItem = {
    /** Must be 'ExperimentMetric'. */
    kind: PatchedExperimentApiMetricsSecondaryItemKind
    /** Type of metric measurement. */
    metric_type: PatchedExperimentApiMetricsSecondaryItemMetricType
    /** Human-readable metric name. */
    name?: string
    /** Unique identifier for the metric. Auto-generated if not provided. */
    uuid?: string
    /** For mean metrics: EventsNode with 'kind' and 'event' fields. */
    source?: PatchedExperimentApiMetricsSecondaryItemSource
    /** For funnel metrics: array of EventsNode/ActionsNode steps. */
    series?: PatchedExperimentApiMetricsSecondaryItemSeriesItem[]
    /** For ratio metrics: the numerator EventsNode. */
    numerator?: PatchedExperimentApiMetricsSecondaryItemNumerator
    /** For ratio metrics: the denominator EventsNode. */
    denominator?: PatchedExperimentApiMetricsSecondaryItemDenominator
    /** Whether higher or lower values indicate success. */
    goal?: PatchedExperimentApiMetricsSecondaryItemGoal
    /** Conversion window duration. */
    conversion_window?: number
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
    /** Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. */
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
    /**
     * Configuration object containing variant definitions (feature_flag_variants) and minimum detectable effect.
     * @nullable
     */
    parameters?: PatchedExperimentApiParameters
    secondary_metrics?: unknown | null
    readonly saved_metrics?: readonly ExperimentToSavedMetricApi[]
    /**
     * IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary).
     * @nullable
     */
    saved_metrics_ids?: PatchedExperimentApiSavedMetricsIdsItem[] | null
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
    /**
     * Exposure configuration including filter test accounts and custom exposure events.
     * @nullable
     */
    exposure_criteria?: PatchedExperimentApiExposureCriteria
    /**
     * Primary experiment metrics array. Each metric defines what to measure (e.g., mean, funnel, ratio).
     * @nullable
     */
    metrics?: PatchedExperimentApiMetricsItem[] | null
    /**
     * Secondary experiment metrics array for additional measurements.
     * @nullable
     */
    metrics_secondary?: PatchedExperimentApiMetricsSecondaryItem[] | null
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
