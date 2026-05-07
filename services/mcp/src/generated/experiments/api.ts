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

export const experimentsCreateBodyParametersOneFeatureFlagVariantsOneItemNameDefault = null
export const experimentsCreateBodyParametersOneFeatureFlagVariantsOneItemRolloutPercentageDefault = null
export const experimentsCreateBodyParametersOneFeatureFlagVariantsOneItemSplitPercentDefault = null
export const experimentsCreateBodyParametersOneFeatureFlagVariantsDefault = null
export const experimentsCreateBodyParametersOneMinimumDetectableEffectDefault = null
export const experimentsCreateBodyParametersOneRolloutPercentageDefault = null
export const experimentsCreateBodyArchivedDefault = false
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOneKindDefault = `ExperimentEventExposureConfig`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemLabelDefault = null
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault = `exact`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault = `event`
export const experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemValueDefault = null
export const experimentsCreateBodyExposureCriteriaOneExposureConfigDefault = null
export const experimentsCreateBodyExposureCriteriaOneFilterTestAccountsDefault = null
export const experimentsCreateBodyMetricsOneItemCompletionEventOneEventDefault = null
export const experimentsCreateBodyMetricsOneItemCompletionEventOneIdDefault = null
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesDefault = null
export const experimentsCreateBodyMetricsOneItemCompletionEventDefault = null
export const experimentsCreateBodyMetricsOneItemConversionWindowDefault = null
export const experimentsCreateBodyMetricsOneItemDenominatorOneEventDefault = null
export const experimentsCreateBodyMetricsOneItemDenominatorOneIdDefault = null
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesDefault = null
export const experimentsCreateBodyMetricsOneItemDenominatorDefault = null
export const experimentsCreateBodyMetricsOneItemGoalDefault = null
export const experimentsCreateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsCreateBodyMetricsOneItemNameDefault = null
export const experimentsCreateBodyMetricsOneItemNumeratorOneEventDefault = null
export const experimentsCreateBodyMetricsOneItemNumeratorOneIdDefault = null
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesDefault = null
export const experimentsCreateBodyMetricsOneItemNumeratorDefault = null
export const experimentsCreateBodyMetricsOneItemRetentionWindowEndDefault = null
export const experimentsCreateBodyMetricsOneItemRetentionWindowStartDefault = null
export const experimentsCreateBodyMetricsOneItemRetentionWindowUnitDefault = null
export const experimentsCreateBodyMetricsOneItemSeriesOneItemEventDefault = null
export const experimentsCreateBodyMetricsOneItemSeriesOneItemIdDefault = null
export const experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesDefault = null
export const experimentsCreateBodyMetricsOneItemSeriesDefault = null
export const experimentsCreateBodyMetricsOneItemSourceOneEventDefault = null
export const experimentsCreateBodyMetricsOneItemSourceOneIdDefault = null
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsOneItemSourceOnePropertiesDefault = null
export const experimentsCreateBodyMetricsOneItemSourceDefault = null
export const experimentsCreateBodyMetricsOneItemStartEventOneEventDefault = null
export const experimentsCreateBodyMetricsOneItemStartEventOneIdDefault = null
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsOneItemStartEventOnePropertiesDefault = null
export const experimentsCreateBodyMetricsOneItemStartEventDefault = null
export const experimentsCreateBodyMetricsOneItemStartHandlingDefault = null
export const experimentsCreateBodyMetricsOneItemUuidDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOneEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOneIdDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemCompletionEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemConversionWindowDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOneEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOneIdDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemDenominatorDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemGoalDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsCreateBodyMetricsSecondaryOneItemNameDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOneEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOneIdDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemNumeratorDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemRetentionWindowEndDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemRetentionWindowStartDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemRetentionWindowUnitDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemIdDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSeriesDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOneEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOneIdDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemSourceDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOneEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOneIdDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemLabelDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemValueDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemStartEventDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemStartHandlingDefault = null
export const experimentsCreateBodyMetricsSecondaryOneItemUuidDefault = null
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
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        feature_flag_key: zod
            .string()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .union([
                zod.object({
                    feature_flag_variants: zod
                        .union([
                            zod.array(
                                zod.object({
                                    key: zod.string().describe("Variant key, e.g. 'control', 'test', 'variant_a'."),
                                    name: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            experimentsCreateBodyParametersOneFeatureFlagVariantsOneItemNameDefault
                                        )
                                        .describe('Human-readable variant name.'),
                                    rollout_percentage: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            experimentsCreateBodyParametersOneFeatureFlagVariantsOneItemRolloutPercentageDefault
                                        ),
                                    split_percent: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            experimentsCreateBodyParametersOneFeatureFlagVariantsOneItemSplitPercentDefault
                                        )
                                        .describe(
                                            'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                        ),
                                })
                            ),
                            zod.null(),
                        ])
                        .default(experimentsCreateBodyParametersOneFeatureFlagVariantsDefault)
                        .describe('Experiment variants. If not specified, defaults to a 50/50 control/test split.'),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .default(experimentsCreateBodyParametersOneMinimumDetectableEffectDefault)
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                        ),
                    rollout_percentage: zod
                        .union([zod.number(), zod.null()])
                        .default(experimentsCreateBodyParametersOneRolloutPercentageDefault)
                        .describe(
                            'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                "Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power."
            ),
        secondary_metrics: zod.unknown().optional(),
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
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.null()])
            .optional()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .union([
                zod.object({
                    exposure_config: zod
                        .union([
                            zod.object({
                                event: zod.string().describe('Custom exposure event name.'),
                                kind: zod
                                    .literal('ExperimentEventExposureConfig')
                                    .default(experimentsCreateBodyExposureCriteriaOneExposureConfigOneKindDefault),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemLabelDefault
                                                ),
                                            operator: zod
                                                .union([
                                                    zod.enum([
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
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .literal('event')
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
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemValueDefault
                                                ),
                                        })
                                    )
                                    .describe('Event property filters. Pass an empty array if no filters needed.'),
                            }),
                            zod.null(),
                        ])
                        .default(experimentsCreateBodyExposureCriteriaOneExposureConfigDefault),
                    filterTestAccounts: zod
                        .union([zod.boolean(), zod.null()])
                        .default(experimentsCreateBodyExposureCriteriaOneFilterTestAccountsDefault),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemCompletionEventOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemCompletionEventOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsOneItemCompletionEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsOneItemCompletionEventDefault)
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemConversionWindowDefault)
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemDenominatorOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemDenominatorOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(experimentsCreateBodyMetricsOneItemDenominatorOnePropertiesDefault)
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsOneItemDenominatorDefault)
                                .describe('For ratio metrics: denominator source.'),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemGoalDefault)
                                .describe('Whether higher or lower values indicate success.'),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsCreateBodyMetricsOneItemKindDefault),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemNameDefault)
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemNumeratorOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemNumeratorOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(experimentsCreateBodyMetricsOneItemNumeratorOnePropertiesDefault)
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsOneItemNumeratorDefault)
                                .describe('For ratio metrics: numerator source.'),
                            retention_window_end: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemRetentionWindowEndDefault),
                            retention_window_start: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemRetentionWindowStartDefault),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemRetentionWindowUnitDefault),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .default(experimentsCreateBodyMetricsOneItemSeriesOneItemEventDefault)
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(experimentsCreateBodyMetricsOneItemSeriesOneItemIdDefault)
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod
                                                                .union([zod.string(), zod.null()])
                                                                .default(
                                                                    experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemLabelDefault
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemValueDefault
                                                                ),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsCreateBodyMetricsOneItemSeriesOneItemPropertiesDefault
                                                )
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsOneItemSeriesDefault)
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemSourceOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemSourceOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemSourceOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(experimentsCreateBodyMetricsOneItemSourceOnePropertiesDefault)
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsOneItemSourceDefault)
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemStartEventOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsOneItemStartEventOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsOneItemStartEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(experimentsCreateBodyMetricsOneItemStartEventOnePropertiesDefault)
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsOneItemStartEventDefault)
                                .describe('For retention metrics: start event.'),
                            start_handling: zod
                                .union([zod.enum(['first_seen', 'last_seen']), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemStartHandlingDefault),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsCreateBodyMetricsOneItemUuidDefault)
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project."
            ),
        metrics_secondary: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemCompletionEventDefault)
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemConversionWindowDefault)
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemDenominatorDefault)
                                .describe('For ratio metrics: denominator source.'),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemGoalDefault)
                                .describe('Whether higher or lower values indicate success.'),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsCreateBodyMetricsSecondaryOneItemKindDefault),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemNameDefault)
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsSecondaryOneItemNumeratorOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemNumeratorDefault)
                                .describe('For ratio metrics: numerator source.'),
                            retention_window_end: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemRetentionWindowEndDefault),
                            retention_window_start: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemRetentionWindowStartDefault),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemRetentionWindowUnitDefault),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemEventDefault
                                                )
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemIdDefault
                                                )
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod
                                                                .union([zod.string(), zod.null()])
                                                                .default(
                                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemLabelDefault
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemValueDefault
                                                                ),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesDefault
                                                )
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemSeriesDefault)
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsCreateBodyMetricsSecondaryOneItemSourceOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsSecondaryOneItemSourceOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemSourceOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemSourceDefault)
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsCreateBodyMetricsSecondaryOneItemStartEventOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemStartEventDefault)
                                .describe('For retention metrics: start event.'),
                            start_handling: zod
                                .union([zod.enum(['first_seen', 'last_seen']), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemStartHandlingDefault),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsCreateBodyMetricsSecondaryOneItemUuidDefault)
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().optional(),
        scheduling_config: zod.unknown().optional(),
        allow_unknown_events: zod.boolean().default(experimentsCreateBodyAllowUnknownEventsDefault),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().optional(),
        secondary_metrics_ordered_uuids: zod.unknown().optional(),
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

export const experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsOneItemNameDefault = null
export const experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsOneItemRolloutPercentageDefault = null
export const experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsOneItemSplitPercentDefault = null
export const experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsDefault = null
export const experimentsPartialUpdateBodyParametersOneMinimumDetectableEffectDefault = null
export const experimentsPartialUpdateBodyParametersOneRolloutPercentageDefault = null
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOneKindDefault = `ExperimentEventExposureConfig`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemLabelDefault = null
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault = `event`
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemValueDefault = null
export const experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigDefault = null
export const experimentsPartialUpdateBodyExposureCriteriaOneFilterTestAccountsDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemCompletionEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemConversionWindowDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemDenominatorDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemGoalDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsPartialUpdateBodyMetricsOneItemNameDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemNumeratorDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemRetentionWindowEndDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemRetentionWindowStartDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemRetentionWindowUnitDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemIdDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSeriesDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSourceOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSourceOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemSourceDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemStartEventDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemStartHandlingDefault = null
export const experimentsPartialUpdateBodyMetricsOneItemUuidDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemConversionWindowDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemGoalDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNameDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemRetentionWindowEndDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemRetentionWindowStartDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemRetentionWindowUnitDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemIdDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOneEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOneIdDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemLabelDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemValueDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemStartHandlingDefault = null
export const experimentsPartialUpdateBodyMetricsSecondaryOneItemUuidDefault = null

export const ExperimentsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(experimentsPartialUpdateBodyNameMax).optional().describe('Name of the experiment.'),
        description: zod
            .string()
            .max(experimentsPartialUpdateBodyDescriptionMax)
            .nullish()
            .describe('Description of the experiment hypothesis and expected outcomes.'),
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        feature_flag_key: zod
            .string()
            .optional()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .union([
                zod.object({
                    feature_flag_variants: zod
                        .union([
                            zod.array(
                                zod.object({
                                    key: zod.string().describe("Variant key, e.g. 'control', 'test', 'variant_a'."),
                                    name: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsOneItemNameDefault
                                        )
                                        .describe('Human-readable variant name.'),
                                    rollout_percentage: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsOneItemRolloutPercentageDefault
                                        ),
                                    split_percent: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsOneItemSplitPercentDefault
                                        )
                                        .describe(
                                            'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                        ),
                                })
                            ),
                            zod.null(),
                        ])
                        .default(experimentsPartialUpdateBodyParametersOneFeatureFlagVariantsDefault)
                        .describe('Experiment variants. If not specified, defaults to a 50/50 control/test split.'),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .default(experimentsPartialUpdateBodyParametersOneMinimumDetectableEffectDefault)
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                        ),
                    rollout_percentage: zod
                        .union([zod.number(), zod.null()])
                        .default(experimentsPartialUpdateBodyParametersOneRolloutPercentageDefault)
                        .describe(
                            'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                "Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power."
            ),
        secondary_metrics: zod.unknown().optional(),
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
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.null()])
            .optional()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .union([
                zod.object({
                    exposure_config: zod
                        .union([
                            zod.object({
                                event: zod.string().describe('Custom exposure event name.'),
                                kind: zod
                                    .literal('ExperimentEventExposureConfig')
                                    .default(
                                        experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOneKindDefault
                                    ),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemLabelDefault
                                                ),
                                            operator: zod
                                                .union([
                                                    zod.enum([
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
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .literal('event')
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
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigOnePropertiesItemValueDefault
                                                ),
                                        })
                                    )
                                    .describe('Event property filters. Pass an empty array if no filters needed.'),
                            }),
                            zod.null(),
                        ])
                        .default(experimentsPartialUpdateBodyExposureCriteriaOneExposureConfigDefault),
                    filterTestAccounts: zod
                        .union([zod.boolean(), zod.null()])
                        .default(experimentsPartialUpdateBodyExposureCriteriaOneFilterTestAccountsDefault),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemCompletionEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsOneItemCompletionEventDefault)
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemConversionWindowDefault)
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsPartialUpdateBodyMetricsOneItemDenominatorOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemDenominatorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsOneItemDenominatorDefault)
                                .describe('For ratio metrics: denominator source.'),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemGoalDefault)
                                .describe('Whether higher or lower values indicate success.'),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsPartialUpdateBodyMetricsOneItemKindDefault),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemNameDefault)
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsPartialUpdateBodyMetricsOneItemNumeratorOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsPartialUpdateBodyMetricsOneItemNumeratorOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemNumeratorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsOneItemNumeratorDefault)
                                .describe('For ratio metrics: numerator source.'),
                            retention_window_end: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemRetentionWindowEndDefault),
                            retention_window_start: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemRetentionWindowStartDefault),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemRetentionWindowUnitDefault),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemEventDefault
                                                )
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemIdDefault
                                                )
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod
                                                                .union([zod.string(), zod.null()])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemLabelDefault
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesOneItemValueDefault
                                                                ),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsOneItemSeriesOneItemPropertiesDefault
                                                )
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsOneItemSeriesDefault)
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsPartialUpdateBodyMetricsOneItemSourceOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsPartialUpdateBodyMetricsOneItemSourceOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemSourceOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsOneItemSourceDefault)
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsPartialUpdateBodyMetricsOneItemStartEventOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsOneItemStartEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsOneItemStartEventDefault)
                                .describe('For retention metrics: start event.'),
                            start_handling: zod
                                .union([zod.enum(['first_seen', 'last_seen']), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemStartHandlingDefault),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsOneItemUuidDefault)
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project."
            ),
        metrics_secondary: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemCompletionEventDefault)
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemConversionWindowDefault)
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemDenominatorDefault)
                                .describe('For ratio metrics: denominator source.'),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemGoalDefault)
                                .describe('Whether higher or lower values indicate success.'),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemKindDefault),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemNameDefault)
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemNumeratorDefault)
                                .describe('For ratio metrics: numerator source.'),
                            retention_window_end: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemRetentionWindowEndDefault),
                            retention_window_start: zod
                                .union([zod.number(), zod.null()])
                                .default(
                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemRetentionWindowStartDefault
                                ),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemRetentionWindowUnitDefault),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemEventDefault
                                                )
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemIdDefault
                                                )
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod
                                                                .union([zod.string(), zod.null()])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemLabelDefault
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemValueDefault
                                                                ),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesDefault
                                                )
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemSeriesDefault)
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemSourceDefault)
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemStartEventDefault)
                                .describe('For retention metrics: start event.'),
                            start_handling: zod
                                .union([zod.enum(['first_seen', 'last_seen']), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemStartHandlingDefault),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsPartialUpdateBodyMetricsSecondaryOneItemUuidDefault)
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().optional(),
        scheduling_config: zod.unknown().optional(),
        allow_unknown_events: zod.boolean().optional(),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().optional(),
        secondary_metrics_ordered_uuids: zod.unknown().optional(),
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

export const experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsOneItemNameDefault = null
export const experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsOneItemRolloutPercentageDefault = null
export const experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsOneItemSplitPercentDefault = null
export const experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsDefault = null
export const experimentsDuplicateCreateBodyParametersOneMinimumDetectableEffectDefault = null
export const experimentsDuplicateCreateBodyParametersOneRolloutPercentageDefault = null
export const experimentsDuplicateCreateBodyArchivedDefault = false
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOneKindDefault = `ExperimentEventExposureConfig`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemLabelDefault = null
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemValueDefault = null
export const experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigDefault = null
export const experimentsDuplicateCreateBodyExposureCriteriaOneFilterTestAccountsDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemCompletionEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemConversionWindowDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemDenominatorDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemGoalDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemKindDefault = `ExperimentMetric`
export const experimentsDuplicateCreateBodyMetricsOneItemNameDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemNumeratorDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemRetentionWindowEndDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemRetentionWindowStartDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemRetentionWindowUnitDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemIdDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSeriesDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemSourceDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemStartEventDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemStartHandlingDefault = null
export const experimentsDuplicateCreateBodyMetricsOneItemUuidDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemConversionWindowDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemGoalDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemKindDefault = `ExperimentMetric`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNameDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemRetentionWindowEndDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemRetentionWindowStartDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemRetentionWindowUnitDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemIdDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOneEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOneIdDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemLabelDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault = `exact`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault = `event`
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemValueDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartHandlingDefault = null
export const experimentsDuplicateCreateBodyMetricsSecondaryOneItemUuidDefault = null
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
        start_date: zod.iso.datetime({ offset: true }).nullish(),
        end_date: zod.iso.datetime({ offset: true }).nullish(),
        feature_flag_key: zod
            .string()
            .describe(
                "Unique key for the experiment's feature flag. Letters, numbers, hyphens, and underscores only. Search existing flags with the feature-flags-get-all tool first — reuse an existing flag when possible."
            ),
        holdout_id: zod.number().nullish().describe('ID of a holdout group to exclude from the experiment.'),
        parameters: zod
            .union([
                zod.object({
                    feature_flag_variants: zod
                        .union([
                            zod.array(
                                zod.object({
                                    key: zod.string().describe("Variant key, e.g. 'control', 'test', 'variant_a'."),
                                    name: zod
                                        .union([zod.string(), zod.null()])
                                        .default(
                                            experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsOneItemNameDefault
                                        )
                                        .describe('Human-readable variant name.'),
                                    rollout_percentage: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsOneItemRolloutPercentageDefault
                                        ),
                                    split_percent: zod
                                        .union([zod.number(), zod.null()])
                                        .default(
                                            experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsOneItemSplitPercentDefault
                                        )
                                        .describe(
                                            'Percentage of users assigned to this variant (0–100). All variants must sum to 100. One of split_percent (recommended) or rollout_percentage must be provided.'
                                        ),
                                })
                            ),
                            zod.null(),
                        ])
                        .default(experimentsDuplicateCreateBodyParametersOneFeatureFlagVariantsDefault)
                        .describe('Experiment variants. If not specified, defaults to a 50/50 control/test split.'),
                    minimum_detectable_effect: zod
                        .union([zod.number(), zod.null()])
                        .default(experimentsDuplicateCreateBodyParametersOneMinimumDetectableEffectDefault)
                        .describe(
                            'Minimum detectable effect as a percentage. Lower values need more users but catch smaller changes. Suggest 20–30% for most experiments.'
                        ),
                    rollout_percentage: zod
                        .union([zod.number(), zod.null()])
                        .default(experimentsDuplicateCreateBodyParametersOneRolloutPercentageDefault)
                        .describe(
                            'Overall rollout percentage (0-100). Controls what fraction of all users enter the experiment. Users outside the rollout never see any variant and are excluded from analysis. Default: 100.'
                        ),
                }),
                zod.null(),
            ])
            .optional()
            .describe(
                "Variant definitions and rollout configuration. Set feature_flag_variants to customize the split (default: 50/50 control/test). Each variant needs a key and split_percent (the variant's share of traffic); percentages must sum to 100. Set rollout_percentage (0-100, default 100) to limit what fraction of users enter the experiment. Set minimum_detectable_effect (percentage, suggest 20-30) to control statistical power."
            ),
        secondary_metrics: zod.unknown().optional(),
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
            .union([zod.enum(['web', 'product']).describe('* `web` - web\n* `product` - product'), zod.null()])
            .optional()
            .describe(
                'Experiment type: web for frontend UI changes, product for backend/API changes.\n\n* `web` - web\n* `product` - product'
            ),
        exposure_criteria: zod
            .union([
                zod.object({
                    exposure_config: zod
                        .union([
                            zod.object({
                                event: zod.string().describe('Custom exposure event name.'),
                                kind: zod
                                    .literal('ExperimentEventExposureConfig')
                                    .default(
                                        experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOneKindDefault
                                    ),
                                properties: zod
                                    .array(
                                        zod.object({
                                            key: zod.string(),
                                            label: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemLabelDefault
                                                ),
                                            operator: zod
                                                .union([
                                                    zod.enum([
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
                                                    ]),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemOperatorDefault
                                                ),
                                            type: zod
                                                .literal('event')
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
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigOnePropertiesItemValueDefault
                                                ),
                                        })
                                    )
                                    .describe('Event property filters. Pass an empty array if no filters needed.'),
                            }),
                            zod.null(),
                        ])
                        .default(experimentsDuplicateCreateBodyExposureCriteriaOneExposureConfigDefault),
                    filterTestAccounts: zod
                        .union([zod.boolean(), zod.null()])
                        .default(experimentsDuplicateCreateBodyExposureCriteriaOneFilterTestAccountsDefault),
                }),
                zod.null(),
            ])
            .optional()
            .describe('Exposure configuration including filter test accounts and custom exposure events.'),
        metrics: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemCompletionEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemCompletionEventDefault)
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemConversionWindowDefault)
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemDenominatorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemDenominatorDefault)
                                .describe('For ratio metrics: denominator source.'),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemGoalDefault)
                                .describe('Whether higher or lower values indicate success.'),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsDuplicateCreateBodyMetricsOneItemKindDefault),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemNameDefault)
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsDuplicateCreateBodyMetricsOneItemNumeratorOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemNumeratorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemNumeratorDefault)
                                .describe('For ratio metrics: numerator source.'),
                            retention_window_end: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemRetentionWindowEndDefault),
                            retention_window_start: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemRetentionWindowStartDefault),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemRetentionWindowUnitDefault),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemEventDefault
                                                )
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemIdDefault
                                                )
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod
                                                                .union([zod.string(), zod.null()])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemLabelDefault
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesOneItemValueDefault
                                                                ),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsOneItemSeriesOneItemPropertiesDefault
                                                )
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemSeriesDefault)
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(experimentsDuplicateCreateBodyMetricsOneItemSourceOneEventDefault)
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsDuplicateCreateBodyMetricsOneItemSourceOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemSourceOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemSourceDefault)
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(experimentsDuplicateCreateBodyMetricsOneItemStartEventOneIdDefault)
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsOneItemStartEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemStartEventDefault)
                                .describe('For retention metrics: start event.'),
                            start_handling: zod
                                .union([zod.enum(['first_seen', 'last_seen']), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemStartHandlingDefault),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsOneItemUuidDefault)
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe(
                "Primary experiment metrics. Each metric must have kind='ExperimentMetric' and a metric_type: 'mean' (set source to an EventsNode with an event name), 'funnel' (set series to an array of EventsNode steps), 'ratio' (set numerator and denominator EventsNode entries), or 'retention' (set start_event and completion_event). Use the event-definitions-list tool to find available events in the project."
            ),
        metrics_secondary: zod
            .union([
                zod
                    .array(
                        zod.object({
                            completion_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemCompletionEventDefault)
                                .describe('For retention metrics: completion event.'),
                            conversion_window: zod
                                .union([zod.number(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemConversionWindowDefault)
                                .describe('Conversion window duration.'),
                            denominator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemDenominatorDefault)
                                .describe('For ratio metrics: denominator source.'),
                            goal: zod
                                .union([zod.enum(['increase', 'decrease']), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemGoalDefault)
                                .describe('Whether higher or lower values indicate success.'),
                            kind: zod
                                .literal('ExperimentMetric')
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemKindDefault),
                            metric_type: zod.enum(['funnel', 'mean', 'ratio', 'retention']),
                            name: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemNameDefault)
                                .describe('Human-readable metric name.'),
                            numerator: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemNumeratorDefault)
                                .describe('For ratio metrics: numerator source.'),
                            retention_window_end: zod
                                .union([zod.number(), zod.null()])
                                .default(
                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemRetentionWindowEndDefault
                                ),
                            retention_window_start: zod
                                .union([zod.number(), zod.null()])
                                .default(
                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemRetentionWindowStartDefault
                                ),
                            retention_window_unit: zod
                                .union([zod.enum(['second', 'minute', 'hour', 'day', 'week', 'month']), zod.null()])
                                .default(
                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemRetentionWindowUnitDefault
                                ),
                            series: zod
                                .union([
                                    zod.array(
                                        zod.object({
                                            event: zod
                                                .union([zod.string(), zod.null()])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemEventDefault
                                                )
                                                .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                            id: zod
                                                .union([zod.number(), zod.null()])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemIdDefault
                                                )
                                                .describe('Action ID. Required for ActionsNode.'),
                                            kind: zod.enum(['EventsNode', 'ActionsNode']),
                                            properties: zod
                                                .union([
                                                    zod.array(
                                                        zod.object({
                                                            key: zod.string(),
                                                            label: zod
                                                                .union([zod.string(), zod.null()])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemLabelDefault
                                                                ),
                                                            operator: zod
                                                                .union([
                                                                    zod.enum([
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
                                                                    ]),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemOperatorDefault
                                                                ),
                                                            type: zod
                                                                .literal('event')
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemTypeDefault
                                                                )
                                                                .describe('Event properties'),
                                                            value: zod
                                                                .union([
                                                                    zod.array(
                                                                        zod.union([
                                                                            zod.string(),
                                                                            zod.number(),
                                                                            zod.boolean(),
                                                                        ])
                                                                    ),
                                                                    zod.string(),
                                                                    zod.number(),
                                                                    zod.boolean(),
                                                                    zod.null(),
                                                                ])
                                                                .default(
                                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesOneItemValueDefault
                                                                ),
                                                        })
                                                    ),
                                                    zod.null(),
                                                ])
                                                .default(
                                                    experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesOneItemPropertiesDefault
                                                )
                                                .describe('Event property filters to narrow which events are counted.'),
                                        })
                                    ),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemSeriesDefault)
                                .describe('For funnel metrics: array of EventsNode/ActionsNode steps.'),
                            source: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemSourceDefault)
                                .describe('For mean metrics: event source.'),
                            start_event: zod
                                .union([
                                    zod.object({
                                        event: zod
                                            .union([zod.string(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOneEventDefault
                                            )
                                            .describe("Event name, e.g. '$pageview'. Required for EventsNode."),
                                        id: zod
                                            .union([zod.number(), zod.null()])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOneIdDefault
                                            )
                                            .describe('Action ID. Required for ActionsNode.'),
                                        kind: zod.enum(['EventsNode', 'ActionsNode']),
                                        properties: zod
                                            .union([
                                                zod.array(
                                                    zod.object({
                                                        key: zod.string(),
                                                        label: zod
                                                            .union([zod.string(), zod.null()])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemLabelDefault
                                                            ),
                                                        operator: zod
                                                            .union([
                                                                zod.enum([
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
                                                                ]),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemOperatorDefault
                                                            ),
                                                        type: zod
                                                            .literal('event')
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemTypeDefault
                                                            )
                                                            .describe('Event properties'),
                                                        value: zod
                                                            .union([
                                                                zod.array(
                                                                    zod.union([
                                                                        zod.string(),
                                                                        zod.number(),
                                                                        zod.boolean(),
                                                                    ])
                                                                ),
                                                                zod.string(),
                                                                zod.number(),
                                                                zod.boolean(),
                                                                zod.null(),
                                                            ])
                                                            .default(
                                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesOneItemValueDefault
                                                            ),
                                                    })
                                                ),
                                                zod.null(),
                                            ])
                                            .default(
                                                experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventOnePropertiesDefault
                                            )
                                            .describe('Event property filters to narrow which events are counted.'),
                                    }),
                                    zod.null(),
                                ])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartEventDefault)
                                .describe('For retention metrics: start event.'),
                            start_handling: zod
                                .union([zod.enum(['first_seen', 'last_seen']), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemStartHandlingDefault),
                            uuid: zod
                                .union([zod.string(), zod.null()])
                                .default(experimentsDuplicateCreateBodyMetricsSecondaryOneItemUuidDefault)
                                .describe('Unique identifier. Auto-generated if omitted.'),
                        })
                    )
                    .describe('List wrapper for OpenAPI schema generation — the field stores an array of metrics.'),
                zod.null(),
            ])
            .optional()
            .describe('Secondary metrics for additional measurements. Same format as primary metrics.'),
        stats_config: zod.unknown().optional(),
        scheduling_config: zod.unknown().optional(),
        allow_unknown_events: zod.boolean().default(experimentsDuplicateCreateBodyAllowUnknownEventsDefault),
        _create_in_folder: zod.string().optional(),
        conclusion: zod
            .union([
                zod
                    .enum(['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'])
                    .describe(
                        '* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
                    ),
                zod.null(),
            ])
            .optional()
            .describe(
                'Experiment conclusion: won, lost, inconclusive, stopped_early, or invalid.\n\n* `won` - won\n* `lost` - lost\n* `inconclusive` - inconclusive\n* `stopped_early` - stopped_early\n* `invalid` - invalid'
            ),
        conclusion_comment: zod.string().nullish().describe('Comment about the experiment conclusion.'),
        primary_metrics_ordered_uuids: zod.unknown().optional(),
        secondary_metrics_ordered_uuids: zod.unknown().optional(),
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
            zod.null(),
        ])
        .optional()
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
            zod.null(),
        ])
        .optional()
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
