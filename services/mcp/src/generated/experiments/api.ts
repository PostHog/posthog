/**
 * Auto-generated from the Django backend OpenAPI schema.
 * MCP service uses these Zod schemas for generated tool handlers.
 * To regenerate: hogli build:openapi
 *
 * PostHog API - MCP 16 enabled ops
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * List experiments for the current project. Supports filtering by status and archival state.
 */
export const ExperimentsListParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsListQueryParams = /* @__PURE__ */ zod.object({
    archived: zod.boolean().optional().describe('Filter by archived state. Defaults to non-archived experiments only.'),
    created_by_id: zod.number().optional().describe('Filter to experiments created by the given user ID.'),
    feature_flag_id: zod.number().optional().describe('Filter to experiments linked to the given feature flag ID.'),
    limit: zod.number().optional().describe('Number of results to return per page.'),
    offset: zod.number().optional().describe('The initial index from which to return the results.'),
    order: zod
        .string()
        .optional()
        .describe(
            "Field to order by. Prefix with '-' for descending. Allowlisted fields include name, created_at, updated_at, start_date, end_date, duration, and status."
        ),
    search: zod.string().optional().describe('Free-text search applied to the experiment name (case-insensitive).'),
    status: zod
        .enum(['all', 'complete', 'draft', 'paused', 'running', 'stopped'])
        .optional()
        .describe(
            'Filter by experiment status. "running" and "paused" are mutually exclusive: "running" returns launched experiments with an active feature flag, "paused" returns launched experiments whose feature flag is deactivated. "complete" is an alias for "stopped". "all" disables status filtering.'
        ),
})

/**
 * Create a new experiment in draft status with optional metrics.
 */
export const ExperimentsCreateParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsCreateBodyNameMax = 400

export const experimentsCreateBodyDescriptionMax = 3000

export const experimentsCreateBodyArchivedDefault = false
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOneKindDefault = `ExperimentEventExposureConfig`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemSeriesItemPropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemSeriesItemPropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyAllowUnknownEventsDefault = false
export const experimentsCreateBodyUpdateFeatureFlagParamsDefault = false

export const ExperimentsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsCreateBodyNameMax).describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsCreateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        feature_flag_key: zod
            .string()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .object({
                feature_flag_variants: zod
                    .array(
                        zod.object({
                            key: zod.string().describe("Variant key, e.g. 'control', 'test', 'variant_a'."),
                            name: zod.string().nullish().describe('Human-readable variant name.'),
                            rollout_percentage: zod.number().nullish(),
                            split_percent: zod
                                .number()
                                .nullish()
                                .describe(
                                    'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                ),
                        })
                    )
                    .nullish()
                    .describe('Experiment variants. If not specified, defaults to a 50/50 control/test split.'),
                minimum_detectable_effect: zod
                    .number()
                    .nullish()
                    .describe(
                        'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                    ),
                rollout_percentage: zod
                    .number()
                    .nullish()
                    .describe(
                        'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                    ),
            })
            .nullish()
            .describe(
                "Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power."
            ),
        secondary_metrics: zod.unknown().nullish(),
        saved_metrics_ids: zod
            .array(zod.unknown())
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod
            .boolean()
            .default(experimentsCreateBodyArchivedDefault)
            .describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.literal(null)])
            .nullish()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .object({
                exposure_config: zod
                    .object({
                        event: zod.string().describe('Custom exposure event name.'),
                        kind: zod
                            .enum(['ExperimentEventExposureConfig'])
                            .default(experimentsCreateBodyExposureCriteriaOneExposureConfigOneKindDefault),
                        properties: zod
                            .array(
                                zod.object({
                                    key: zod.string(),
                                    label: zod.string().nullish(),
                                    operator: zod
                                        .enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ])
                                        .default(
                                            experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault
                                        ),
                                    type: zod
                                        .enum(['event'])
                                        .default(
                                            experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault
                                        )
                                        .describe('Event properties'),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                        ])
                                        .nullish(),
                                })
                            )
                            .describe('Event property filters. Pass an empty array if no filters needed.'),
                    })
                    .nullish(),
                filterTestAccounts: zod.boolean().nullish(),
            })
            .nullish()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .array(
                zod.object({
                    completion_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: completion event.'),
                    conversion_window: zod.number().nullish().describe('Conversion window duration.'),
                    denominator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: denominator source.'),
                    goal: zod
                        .enum(['increase', 'decrease'])
                        .nullish()
                        .describe('Whether higher or lower values indicate success.'),
                    kind: zod.enum(['ExperimentMetric']).default(experimentsCreateBodyMetricsOneItemKindDefault),
                    metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                    name: zod.string().nullish().describe('Human-readable metric name.'),
                    numerator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: numerator source.'),
                    retention_window_end: zod.number().nullish(),
                    retention_window_start: zod.number().nullish(),
                    retention_window_unit: zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']).nullish(),
                    series: zod
                        .array(
                            zod.object({
                                event: zod
                                    .string()
                                    .nullish()
                                    .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                                kind: zod.enum(['EventsNode', 'ActionsNode']),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod.string().nullish(),
                                            operator: zod
                                                .enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ])
                                                .default(
                                                    experimentsCreateBodyMetricsOneItemSeriesItemPropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .enum(['event'])
                                                .default(
                                                    experimentsCreateBodyMetricsOneItemSeriesItemPropertiesItemTypeDefault
                                                )
                                                .describe('Event properties'),
                                            value: zod
                                                .union([
                                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                    zod.string(),
                                                    zod.number(),
                                                    zod.boolean(),
                                                ])
                                                .nullish(),
                                        })
                                    )
                                    .nullish()
                                    .describe('Event property filters to narrow which events are counted.'),
                            })
                        )
                        .nullish()
                        .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                    source: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For mean metrics: event source.'),
                    start_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: start event.'),
                    start_handling: zod.enum(['first_seen', 'last_seen']).nullish(),
                    uuid: zod.string().nullish().describe('Unique identifier. Auto-generated if omitted.'),
                })
            )
            .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.')
            .nullish()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project."
            ),
        metrics_secondary: zod
            .array(
                zod.object({
                    completion_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: completion event.'),
                    conversion_window: zod.number().nullish().describe('Conversion window duration.'),
                    denominator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: denominator source.'),
                    goal: zod
                        .enum(['increase', 'decrease'])
                        .nullish()
                        .describe('Whether higher or lower values indicate success.'),
                    kind: zod
                        .enum(['ExperimentMetric'])
                        .default(experimentsCreateBodyMetricsSecondaryOneItemKindDefault),
                    metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                    name: zod.string().nullish().describe('Human-readable metric name.'),
                    numerator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: numerator source.'),
                    retention_window_end: zod.number().nullish(),
                    retention_window_start: zod.number().nullish(),
                    retention_window_unit: zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']).nullish(),
                    series: zod
                        .array(
                            zod.object({
                                event: zod
                                    .string()
                                    .nullish()
                                    .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                                kind: zod.enum(['EventsNode', 'ActionsNode']),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod.string().nullish(),
                                            operator: zod
                                                .enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ])
                                                .default(
                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .enum(['event'])
                                                .default(
                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemTypeDefault
                                                )
                                                .describe('Event properties'),
                                            value: zod
                                                .union([
                                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                    zod.string(),
                                                    zod.number(),
                                                    zod.boolean(),
                                                ])
                                                .nullish(),
                                        })
                                    )
                                    .nullish()
                                    .describe('Event property filters to narrow which events are counted.'),
                            })
                        )
                        .nullish()
                        .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                    source: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For mean metrics: event source.'),
                    start_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: start event.'),
                    start_handling: zod.enum(['first_seen', 'last_seen']).nullish(),
                    uuid: zod.string().nullish().describe('Unique identifier. Auto-generated if omitted.'),
                })
            )
            .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.')
            .nullish()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().nullish(),
        scheduling_config: zod.unknown().nullish(),
        allow_unknown_events: zod.boolean().default(experimentsCreateBodyAllowUnknownEventsDefault),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().nullish(),
        secondary_metrics_ordered_uuids: zod.unknown().nullish(),
        only_count_matured_users: zod.boolean().optional(),
        update_feature_flag_params: zod
            .boolean()
            .default(experimentsCreateBodyUpdateFeatureFlagParamsDefault)
            .describe(
                'When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts.'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Retrieve a single experiment by ID, including its current status, metrics, feature flag, and results metadata.
 */
export const ExperimentsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Update an experiment. Use this to modify experiment properties such as name, description, metrics, variants, and configuration. Metrics can be added, changed and removed at any time.
 */
export const ExperimentsPartialUpdateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsPartialUpdateBodyNameMax = 400

export const experimentsPartialUpdateBodyDescriptionMax = 3000

export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOneKindDefault = `ExperimentEventExposureConfig`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemSeriesItemPropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemSeriesItemPropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemTypeDefault = `event`

export const ExperimentsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsPartialUpdateBodyNameMax).optional().describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsPartialUpdateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        feature_flag_key: zod
            .string()
            .optional()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .object({
                feature_flag_variants: zod
                    .array(
                        zod.object({
                            key: zod.string().describe("Variant key, e.g. 'control', 'test', 'variant_a'."),
                            name: zod.string().nullish().describe('Human-readable variant name.'),
                            rollout_percentage: zod.number().nullish(),
                            split_percent: zod
                                .number()
                                .nullish()
                                .describe(
                                    'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                ),
                        })
                    )
                    .nullish()
                    .describe('Experiment variants. If not specified, defaults to a 50/50 control/test split.'),
                minimum_detectable_effect: zod
                    .number()
                    .nullish()
                    .describe(
                        'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                    ),
                rollout_percentage: zod
                    .number()
                    .nullish()
                    .describe(
                        'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                    ),
            })
            .nullish()
            .describe(
                "Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power."
            ),
        secondary_metrics: zod.unknown().nullish(),
        saved_metrics_ids: zod
            .array(zod.unknown())
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod.boolean().optional().describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.literal(null)])
            .nullish()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .object({
                exposure_config: zod
                    .object({
                        event: zod.string().describe('Custom exposure event name.'),
                        kind: zod
                            .enum(['ExperimentEventExposureConfig'])
                            .default(experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOneKindDefault),
                        properties: zod
                            .array(
                                zod.object({
                                    key: zod.string(),
                                    label: zod.string().nullish(),
                                    operator: zod
                                        .enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ])
                                        .default(
                                            experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault
                                        ),
                                    type: zod
                                        .enum(['event'])
                                        .default(
                                            experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault
                                        )
                                        .describe('Event properties'),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                        ])
                                        .nullish(),
                                })
                            )
                            .describe('Event property filters. Pass an empty array if no filters needed.'),
                    })
                    .nullish(),
                filterTestAccounts: zod.boolean().nullish(),
            })
            .nullish()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .array(
                zod.object({
                    completion_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: completion event.'),
                    conversion_window: zod.number().nullish().describe('Conversion window duration.'),
                    denominator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: denominator source.'),
                    goal: zod
                        .enum(['increase', 'decrease'])
                        .nullish()
                        .describe('Whether higher or lower values indicate success.'),
                    kind: zod.enum(['ExperimentMetric']).default(experimentsPartialUpdateBodyMetricsOneItemKindDefault),
                    metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                    name: zod.string().nullish().describe('Human-readable metric name.'),
                    numerator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: numerator source.'),
                    retention_window_end: zod.number().nullish(),
                    retention_window_start: zod.number().nullish(),
                    retention_window_unit: zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']).nullish(),
                    series: zod
                        .array(
                            zod.object({
                                event: zod
                                    .string()
                                    .nullish()
                                    .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                                kind: zod.enum(['EventsNode', 'ActionsNode']),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod.string().nullish(),
                                            operator: zod
                                                .enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesItemPropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .enum(['event'])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesItemPropertiesItemTypeDefault
                                                )
                                                .describe('Event properties'),
                                            value: zod
                                                .union([
                                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                    zod.string(),
                                                    zod.number(),
                                                    zod.boolean(),
                                                ])
                                                .nullish(),
                                        })
                                    )
                                    .nullish()
                                    .describe('Event property filters to narrow which events are counted.'),
                            })
                        )
                        .nullish()
                        .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                    source: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For mean metrics: event source.'),
                    start_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: start event.'),
                    start_handling: zod.enum(['first_seen', 'last_seen']).nullish(),
                    uuid: zod.string().nullish().describe('Unique identifier. Auto-generated if omitted.'),
                })
            )
            .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.')
            .nullish()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project."
            ),
        metrics_secondary: zod
            .array(
                zod.object({
                    completion_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: completion event.'),
                    conversion_window: zod.number().nullish().describe('Conversion window duration.'),
                    denominator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: denominator source.'),
                    goal: zod
                        .enum(['increase', 'decrease'])
                        .nullish()
                        .describe('Whether higher or lower values indicate success.'),
                    kind: zod
                        .enum(['ExperimentMetric'])
                        .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemKindDefault),
                    metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                    name: zod.string().nullish().describe('Human-readable metric name.'),
                    numerator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: numerator source.'),
                    retention_window_end: zod.number().nullish(),
                    retention_window_start: zod.number().nullish(),
                    retention_window_unit: zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']).nullish(),
                    series: zod
                        .array(
                            zod.object({
                                event: zod
                                    .string()
                                    .nullish()
                                    .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                                kind: zod.enum(['EventsNode', 'ActionsNode']),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod.string().nullish(),
                                            operator: zod
                                                .enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .enum(['event'])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemTypeDefault
                                                )
                                                .describe('Event properties'),
                                            value: zod
                                                .union([
                                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                    zod.string(),
                                                    zod.number(),
                                                    zod.boolean(),
                                                ])
                                                .nullish(),
                                        })
                                    )
                                    .nullish()
                                    .describe('Event property filters to narrow which events are counted.'),
                            })
                        )
                        .nullish()
                        .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                    source: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For mean metrics: event source.'),
                    start_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: start event.'),
                    start_handling: zod.enum(['first_seen', 'last_seen']).nullish(),
                    uuid: zod.string().nullish().describe('Unique identifier. Auto-generated if omitted.'),
                })
            )
            .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.')
            .nullish()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().nullish(),
        scheduling_config: zod.unknown().nullish(),
        allow_unknown_events: zod.boolean().optional(),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().nullish(),
        secondary_metrics_ordered_uuids: zod.unknown().nullish(),
        only_count_matured_users: zod.boolean().optional(),
        update_feature_flag_params: zod
            .boolean()
            .optional()
            .describe(
                'When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts.'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * Hard delete of this model is not allowed. Use a patch API call to set "deleted" to true
 */
export const ExperimentsDestroyParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Archive an ended experiment.

Hides the experiment from the default list view. The experiment can be
restored at any time by updating archived=false. Returns 400 if the
experiment is already archived or has not ended yet.
 */
export const ExperimentsArchiveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsDuplicateCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const experimentsDuplicateCreateBodyNameMax = 400

export const experimentsDuplicateCreateBodyDescriptionMax = 3000

export const experimentsDuplicateCreateBodyArchivedDefault = false
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOneKindDefault = `ExperimentEventExposureConfig`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesItemPropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesItemPropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyAllowUnknownEventsDefault = false
export const experimentsDuplicateCreateBodyUpdateFeatureFlagParamsDefault = false

export const ExperimentsDuplicateCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsDuplicateCreateBodyNameMax).describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsDuplicateCreateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({}).nullish(),
        end_date: zod.iso.datetime({}).nullish(),
        feature_flag_key: zod
            .string()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .object({
                feature_flag_variants: zod
                    .array(
                        zod.object({
                            key: zod.string().describe("Variant key, e.g. 'control', 'test', 'variant_a'."),
                            name: zod.string().nullish().describe('Human-readable variant name.'),
                            rollout_percentage: zod.number().nullish(),
                            split_percent: zod
                                .number()
                                .nullish()
                                .describe(
                                    'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                ),
                        })
                    )
                    .nullish()
                    .describe('Experiment variants. If not specified, defaults to a 50/50 control/test split.'),
                minimum_detectable_effect: zod
                    .number()
                    .nullish()
                    .describe(
                        'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                    ),
                rollout_percentage: zod
                    .number()
                    .nullish()
                    .describe(
                        'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                    ),
            })
            .nullish()
            .describe(
                "Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power."
            ),
        secondary_metrics: zod.unknown().nullish(),
        saved_metrics_ids: zod
            .array(zod.unknown())
            .nullish()
            .describe(
                "IDs of shared saved metrics to attach to this experiment. Each item has 'id' (saved metric ID) and 'metadata' with 'type' (primary or secondary)."
            ),
        filters: zod.unknown().optional(),
        archived: zod
            .boolean()
            .default(experimentsDuplicateCreateBodyArchivedDefault)
            .describe('Whether the experiment is archived.'),
        deleted: zod.boolean().nullish(),
        type: zod
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.literal(null)])
            .nullish()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .object({
                exposure_config: zod
                    .object({
                        event: zod.string().describe('Custom exposure event name.'),
                        kind: zod
                            .enum(['ExperimentEventExposureConfig'])
                            .default(experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOneKindDefault),
                        properties: zod
                            .array(
                                zod.object({
                                    key: zod.string(),
                                    label: zod.string().nullish(),
                                    operator: zod
                                        .enum([
                                            'exact',
                                            'is_not',
                                            'icontains',
                                            'not_icontains',
                                            'regex',
                                            'not_regex',
                                            'gt',
                                            'gte',
                                            'lt',
                                            'lte',
                                            'is_set',
                                            'is_not_set',
                                            'is_date_exact',
                                            'is_date_before',
                                            'is_date_after',
                                            'between',
                                            'not_between',
                                            'min',
                                            'max',
                                            'in',
                                            'not_in',
                                            'is_cleaned_path_exact',
                                            'flag_evaluates_to',
                                            'semver_eq',
                                            'semver_neq',
                                            'semver_gt',
                                            'semver_gte',
                                            'semver_lt',
                                            'semver_lte',
                                            'semver_tilde',
                                            'semver_caret',
                                            'semver_wildcard',
                                            'icontains_multi',
                                            'not_icontains_multi',
                                        ])
                                        .default(
                                            experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault
                                        ),
                                    type: zod
                                        .enum(['event'])
                                        .default(
                                            experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault
                                        )
                                        .describe('Event properties'),
                                    value: zod
                                        .union([
                                            zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                            zod.string(),
                                            zod.number(),
                                            zod.boolean(),
                                        ])
                                        .nullish(),
                                })
                            )
                            .describe('Event property filters. Pass an empty array if no filters needed.'),
                    })
                    .nullish(),
                filterTestAccounts: zod.boolean().nullish(),
            })
            .nullish()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .array(
                zod.object({
                    completion_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: completion event.'),
                    conversion_window: zod.number().nullish().describe('Conversion window duration.'),
                    denominator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: denominator source.'),
                    goal: zod
                        .enum(['increase', 'decrease'])
                        .nullish()
                        .describe('Whether higher or lower values indicate success.'),
                    kind: zod
                        .enum(['ExperimentMetric'])
                        .default(experimentsDuplicateCreateBodyMetricsOneItemKindDefault),
                    metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                    name: zod.string().nullish().describe('Human-readable metric name.'),
                    numerator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: numerator source.'),
                    retention_window_end: zod.number().nullish(),
                    retention_window_start: zod.number().nullish(),
                    retention_window_unit: zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']).nullish(),
                    series: zod
                        .array(
                            zod.object({
                                event: zod
                                    .string()
                                    .nullish()
                                    .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                                kind: zod.enum(['EventsNode', 'ActionsNode']),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod.string().nullish(),
                                            operator: zod
                                                .enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesItemPropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .enum(['event'])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesItemPropertiesItemTypeDefault
                                                )
                                                .describe('Event properties'),
                                            value: zod
                                                .union([
                                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                    zod.string(),
                                                    zod.number(),
                                                    zod.boolean(),
                                                ])
                                                .nullish(),
                                        })
                                    )
                                    .nullish()
                                    .describe('Event property filters to narrow which events are counted.'),
                            })
                        )
                        .nullish()
                        .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                    source: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For mean metrics: event source.'),
                    start_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: start event.'),
                    start_handling: zod.enum(['first_seen', 'last_seen']).nullish(),
                    uuid: zod.string().nullish().describe('Unique identifier. Auto-generated if omitted.'),
                })
            )
            .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.')
            .nullish()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project."
            ),
        metrics_secondary: zod
            .array(
                zod.object({
                    completion_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: completion event.'),
                    conversion_window: zod.number().nullish().describe('Conversion window duration.'),
                    denominator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: denominator source.'),
                    goal: zod
                        .enum(['increase', 'decrease'])
                        .nullish()
                        .describe('Whether higher or lower values indicate success.'),
                    kind: zod
                        .enum(['ExperimentMetric'])
                        .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemKindDefault),
                    metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                    name: zod.string().nullish().describe('Human-readable metric name.'),
                    numerator: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For ratio metrics: numerator source.'),
                    retention_window_end: zod.number().nullish(),
                    retention_window_start: zod.number().nullish(),
                    retention_window_unit: zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']).nullish(),
                    series: zod
                        .array(
                            zod.object({
                                event: zod
                                    .string()
                                    .nullish()
                                    .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                                kind: zod.enum(['EventsNode', 'ActionsNode']),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod.string().nullish(),
                                            operator: zod
                                                .enum([
                                                    'exact',
                                                    'is_not',
                                                    'icontains',
                                                    'not_icontains',
                                                    'regex',
                                                    'not_regex',
                                                    'gt',
                                                    'gte',
                                                    'lt',
                                                    'lte',
                                                    'is_set',
                                                    'is_not_set',
                                                    'is_date_exact',
                                                    'is_date_before',
                                                    'is_date_after',
                                                    'between',
                                                    'not_between',
                                                    'min',
                                                    'max',
                                                    'in',
                                                    'not_in',
                                                    'is_cleaned_path_exact',
                                                    'flag_evaluates_to',
                                                    'semver_eq',
                                                    'semver_neq',
                                                    'semver_gt',
                                                    'semver_gte',
                                                    'semver_lt',
                                                    'semver_lte',
                                                    'semver_tilde',
                                                    'semver_caret',
                                                    'semver_wildcard',
                                                    'icontains_multi',
                                                    'not_icontains_multi',
                                                ])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .enum(['event'])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesItemPropertiesItemTypeDefault
                                                )
                                                .describe('Event properties'),
                                            value: zod
                                                .union([
                                                    zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                    zod.string(),
                                                    zod.number(),
                                                    zod.boolean(),
                                                ])
                                                .nullish(),
                                        })
                                    )
                                    .nullish()
                                    .describe('Event property filters to narrow which events are counted.'),
                            })
                        )
                        .nullish()
                        .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                    source: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For mean metrics: event source.'),
                    start_event: zod
                        .object({
                            event: zod
                                .string()
                                .nullish()
                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                            id: zod.number().nullish().describe('Action ID. Required for ActionsNode.'),
                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                            properties: zod
                                .array(
                                    zod.object({
                                        key: zod.string(),
                                        label: zod.string().nullish(),
                                        operator: zod
                                            .enum([
                                                'exact',
                                                'is_not',
                                                'icontains',
                                                'not_icontains',
                                                'regex',
                                                'not_regex',
                                                'gt',
                                                'gte',
                                                'lt',
                                                'lte',
                                                'is_set',
                                                'is_not_set',
                                                'is_date_exact',
                                                'is_date_before',
                                                'is_date_after',
                                                'between',
                                                'not_between',
                                                'min',
                                                'max',
                                                'in',
                                                'not_in',
                                                'is_cleaned_path_exact',
                                                'flag_evaluates_to',
                                                'semver_eq',
                                                'semver_neq',
                                                'semver_gt',
                                                'semver_gte',
                                                'semver_lt',
                                                'semver_lte',
                                                'semver_tilde',
                                                'semver_caret',
                                                'semver_wildcard',
                                                'icontains_multi',
                                                'not_icontains_multi',
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemOperatorDefault
                                            ),
                                        type: zod
                                            .enum(['event'])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesItemTypeDefault
                                            )
                                            .describe('Event properties'),
                                        value: zod
                                            .union([
                                                zod.array(zod.union([zod.string(), zod.number(), zod.boolean()])),
                                                zod.string(),
                                                zod.number(),
                                                zod.boolean(),
                                            ])
                                            .nullish(),
                                    })
                                )
                                .nullish()
                                .describe('Event property filters to narrow which events are counted.'),
                        })
                        .nullish()
                        .describe('For retention metrics: start event.'),
                    start_handling: zod.enum(['first_seen', 'last_seen']).nullish(),
                    uuid: zod.string().nullish().describe('Unique identifier. Auto-generated if omitted.'),
                })
            )
            .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.')
            .nullish()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().nullish(),
        scheduling_config: zod.unknown().nullish(),
        allow_unknown_events: zod.boolean().default(experimentsDuplicateCreateBodyAllowUnknownEventsDefault),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().nullish(),
        secondary_metrics_ordered_uuids: zod.unknown().nullish(),
        only_count_matured_users: zod.boolean().optional(),
        update_feature_flag_params: zod
            .boolean()
            .default(experimentsDuplicateCreateBodyUpdateFeatureFlagParamsDefault)
            .describe(
                'When true, sync feature flag configuration from parameters to the linked feature flag. Draft experiments always sync regardless of update_feature_flag_params, so only required for non-drafts.'
            ),
    })
    .describe('Mixin for serializers to add user access control fields')

/**
 * End a running experiment without shipping a variant.

Sets end_date to now and marks the experiment as stopped. The feature
flag is NOT modified — users continue to see their assigned variants
and exposure events ($feature_flag_called) continue to be recorded.
However, only data up to end_date is included in experiment results.

Use this when:

- You want to freeze the results window without changing which variant
  users see.
- A variant was already shipped manually via the feature flag UI and
  the experiment just needs to be marked complete.

The end_date can be adjusted after ending via PATCH if it needs to be
backdated (e.g. to match when the flag was actually paused).

Other options:
- Use ship_variant to end the experiment AND roll out a single variant to 100%% of users.
- Use pause to deactivate the flag without ending the experiment (stops variant assignment but does not freeze results).

Returns 400 if the experiment is not running.
 */
export const ExperimentsEndCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsEndCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
        ),
    conclusion_comment: zod.string().nullish().describe('Optional comment about the experiment conclusion.'),
})

/**
 * Launch a draft experiment.

Validates the experiment is in draft state, activates its linked feature flag,
sets start_date to the current server time, and transitions the experiment to running.
Returns 400 if the experiment has already been launched or if the feature flag
configuration is invalid (e.g. missing "control" variant or fewer than 2 variants).
 */
export const ExperimentsLaunchCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Pause a running experiment.

Deactivates the linked feature flag so it is no longer returned by the
/decide endpoint. Users fall back to the application default (typically
the control experience), and no new exposure events are recorded (i.e.
$feature_flag_called is not fired).
Returns 400 if the experiment is not running or is already paused.
 */
export const ExperimentsPauseCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Reset an experiment back to draft state.

Clears start/end dates, conclusion, and archived flag. The feature
flag is left unchanged — users continue to see their assigned variants.

Previously collected events still exist but won't be included in
results unless the start date is manually adjusted after re-launch.

Returns 400 if the experiment is already in draft state.
 */
export const ExperimentsResetCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Resume a paused experiment.

Reactivates the linked feature flag so it is returned by /decide again.
Users are re-bucketed deterministically into the same variants they had
before the pause, and exposure tracking resumes.
Returns 400 if the experiment is not running or is not paused.
 */
export const ExperimentsResumeCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Ship a variant to 100% of users and (optionally) end the experiment.

Rewrites the feature flag so that the selected variant is served to everyone.
Existing release conditions (flag groups) are preserved so the change can be
rolled back by deleting the auto-added release condition in the feature flag UI.

Can be called on both running and stopped experiments. If the experiment is
still running, it will also be ended (end_date set and status marked as stopped).
If the experiment has already ended, only the flag is rewritten - this supports
the "end first, ship later" workflow.

If an approval policy requires review before changes on the flag take effect,
the API returns 409 with a change_request_id. The experiment is NOT ended until
the change request is approved and the user retries.

Returns 400 if the experiment is in draft state, the variant_key is not found
on the flag, or the experiment has no linked feature flag.
 */
export const ExperimentsShipVariantCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsShipVariantCreateBody = /* @__PURE__ */ zod.object({
    conclusion: zod
        .union([
            zod
                .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                .describe(
                    '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                ),
            zod.literal(null),
        ])
        .nullish()
        .describe(
            'The conclusion of the experiment.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
        ),
    conclusion_comment: zod.string().nullish().describe('Optional comment about the experiment conclusion.'),
    variant_key: zod.string().describe('The key of the variant to ship to 100% of users.'),
})

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsTimeseriesResultsRetrieveParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

export const ExperimentsTimeseriesResultsRetrieveQueryParams = /* @__PURE__ */ zod.object({
    fingerprint: zod
        .string()
        .describe(
            "Fingerprint of the metric configuration. Available alongside metric_uuid on each metric in the experiment's metrics array."
        ),
    metric_uuid: zod
        .string()
        .describe(
            "UUID of the metric to fetch timeseries for. Available on each metric in the experiment's metrics array."
        ),
})

/**
 * Unarchive an archived experiment.

Restores the experiment to the default list view. Returns 400 if the
experiment is not currently archived.
 */
export const ExperimentsUnarchiveCreateParams = /* @__PURE__ */ zod.object({
    id: zod.number().describe('A unique integer value identifying this experiment.'),
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})

/**
 * Mixin for ViewSets to handle ApprovalRequired exceptions from decorated serializers.

This mixin intercepts ApprovalRequired exceptions raised by the @approval_gate decorator
on serializer methods and converts them into proper HTTP 409 Conflict responses with
change request details.
 */
export const ExperimentsStatsRetrieveParams = /* @__PURE__ */ zod.object({
    project_id: zod
        .string()
        .describe(
            "Project ID of the project you're trying to access. To find the ID of the project, make a call to /api/projects/."
        ),
})
