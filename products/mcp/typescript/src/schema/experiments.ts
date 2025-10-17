import { v4 as uuidv4 } from 'uuid'
import { z } from 'zod'
import { FeatureFlagSchema } from './flags'
import {
    ExperimentCreateSchema as ToolExperimentCreateSchema,
    ExperimentUpdateInputSchema as ToolExperimentUpdateInputSchema,
} from './tool-inputs'

const ExperimentType = ['web', 'product'] as const

const ExperimentConclusion = ['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'] as const

/**
 * This is the schema for the experiment metric base properties.
 * It references the ExperimentMetricBaseProperties type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 *
 * TODO: Add the schemas for FunnelConversionWindowTimeUnit
 */
export const ExperimentMetricBasePropertiesSchema = z.object({
    kind: z.literal('ExperimentMetric'),
    uuid: z.string().optional(),
    name: z.string().optional(),
    conversion_window: z.number().optional(),
    conversion_window_unit: z.any().optional(), // FunnelConversionWindowTimeUnit
})

export type ExperimentMetricBaseProperties = z.infer<typeof ExperimentMetricBasePropertiesSchema>

/**
 * This is the schema for the experiment metric outlier handling.
 * It references the ExperimentMetricOutlierHandling type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentMetricOutlierHandlingSchema = z.object({
    lower_bound_percentile: z.number().optional(),
    upper_bound_percentile: z.number().optional(),
})

export type ExperimentMetricOutlierHandling = z.infer<typeof ExperimentMetricOutlierHandlingSchema>

/**
 * This is the schema for the experiment metric source.
 * It references the ExperimentMetricSource type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 *
 * TODO: Add the schemas for the EventsNode and ActionsNode and ExperimentDataWarehouseNode
 */
export const ExperimentMetricSourceSchema = z.any() // EventsNode | ActionsNode | ExperimentDataWarehouseNode

/**
 * This is the schema for the experiment funnel metric step.
 * It references the ExperimentFunnelMetricStep type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 *
 * TODO: Add the schemas for the EventsNode and ActionsNode
 */
export const ExperimentFunnelMetricStepSchema = z.any() // EventsNode | ActionsNode

/**
 * This is the schema for the experiment mean metric.
 * It references the ExperimentMeanMetric type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentMeanMetricSchema = z
    .object({
        metric_type: z.literal('mean'),
        source: ExperimentMetricSourceSchema,
    })
    .merge(ExperimentMetricBasePropertiesSchema)
    .merge(ExperimentMetricOutlierHandlingSchema)

export type ExperimentMeanMetric = z.infer<typeof ExperimentMeanMetricSchema>

/**
 * This is the schema for the experiment funnel metric.
 * It references the ExperimentFunnelMetric type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentFunnelMetricSchema = z
    .object({
        metric_type: z.literal('funnel'),
        series: z.array(ExperimentFunnelMetricStepSchema),
        funnel_order_type: z.any().optional(), // StepOrderValue
    })
    .merge(ExperimentMetricBasePropertiesSchema)

export type ExperimentFunnelMetric = z.infer<typeof ExperimentFunnelMetricSchema>

/**
 * This is the schema for the experiment ratio metric.
 * It references the ExperimentRatioMetric type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentRatioMetricSchema = z
    .object({
        metric_type: z.literal('ratio'),
        numerator: ExperimentMetricSourceSchema,
        denominator: ExperimentMetricSourceSchema,
    })
    .merge(ExperimentMetricBasePropertiesSchema)

export type ExperimentRatioMetric = z.infer<typeof ExperimentRatioMetricSchema>

/**
 * This is the schema for the experiment metric.
 * It references the ExperimentMetric type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentMetricSchema = z.union([
    ExperimentMeanMetricSchema,
    ExperimentFunnelMetricSchema,
    ExperimentRatioMetricSchema,
])

export type ExperimentMetric = z.infer<typeof ExperimentMetricSchema>

/**
 * This is the schema for the experiment exposure config.
 * It references the ExperimentEventExposureConfig type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentEventExposureConfigSchema = z.object({
    kind: z.literal('ExperimentEventExposureConfig'),
    event: z.string(),
    properties: z.array(z.any()), // this is an array of AnyPropertyFilter
})

/**
 * This is the schema for the experiment exposure criteria.
 * It references the ExperimentExposureCriteria type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentExposureCriteriaSchema = z.object({
    filterTestAccounts: z.boolean().optional(),
    exposure_config: ExperimentEventExposureConfigSchema.optional(),
    multiple_variant_handling: z.enum(['exclude', 'first_seen']).optional(),
})

/**
 * This is the schema for the experiment object.
 * It references the Experiment type from
 * @posthog/frontend/src/types.ts
 */
export const ExperimentSchema = z.object({
    id: z.number(),
    name: z.string(),
    type: z.enum(ExperimentType).nullish(),
    description: z.string().nullish(),
    feature_flag_key: z.string(),
    feature_flag: FeatureFlagSchema.nullish(),
    exposure_cohort: z.number().nullish(),
    exposure_criteria: ExperimentExposureCriteriaSchema.nullish(),
    /**
     * We only type ExperimentMetrics. Legacy metric formats are not validated.
     */
    metrics: z.array(z.union([ExperimentMetricSchema, z.any()])).nullish(),
    metrics_secondary: z.array(z.union([ExperimentMetricSchema, z.any()])).nullish(),
    saved_metrics: z.array(z.any()).nullish(),
    saved_metrics_ids: z.array(z.any()).nullable(),
    parameters: z
        .object({
            feature_flag_variants: z
                .array(
                    z.object({
                        key: z.string(),
                        name: z.string().nullish(),
                        rollout_percentage: z.number().nullish(),
                    })
                )
                .nullish(),
            minimum_detectable_effect: z.number().nullish(),
            recommended_running_time: z.number().nullish(),
            recommended_sample_size: z.number().nullish(),
        })
        .nullish(),
    start_date: z.string().nullish(),
    end_date: z.string().nullish(),
    archived: z.boolean(),
    deleted: z.boolean(),
    created_at: z.string(),
    updated_at: z.string(),
    holdout: z.any().nullish(),
    holdout_id: z.number().nullish(),
    stats_config: z.any().optional(),
    conclusion: z.enum(ExperimentConclusion).nullish(),
    conclusion_comment: z.string().nullish(),
})

export type Experiment = z.infer<typeof ExperimentSchema>

/**
 * Schema for the API payload when creating an experiment
 * This is derived from ExperimentSchema with appropriate omissions
 */
export const ExperimentApiPayloadSchema = ExperimentSchema.omit({
    id: true,
    feature_flag: true,
    exposure_cohort: true,
    exposure_criteria: true,
    saved_metrics: true,
    saved_metrics_ids: true,
    start_date: true,
    end_date: true,
    deleted: true,
    archived: true,
    created_at: true,
    updated_at: true,
    holdout: true,
    stats_config: true,
    conclusion: true,
    conclusion_comment: true,
}).partial()

export type ExperimentApiPayload = z.infer<typeof ExperimentApiPayloadSchema>

/**
 * Schema for the API payload when updating an experiment
 * Derived from ExperimentSchema, omitting fields that cannot be updated
 */
export const ExperimentUpdateApiPayloadSchema = ExperimentSchema.omit({
    id: true,
    feature_flag: true,
    feature_flag_key: true,
    type: true,
    exposure_cohort: true,
    saved_metrics: true,
    deleted: true,
    created_at: true,
    updated_at: true,
    holdout: true,
    holdout_id: true,
}).partial()

export type ExperimentUpdateApiPayload = z.infer<typeof ExperimentUpdateApiPayloadSchema>

/**
 * Helper to conditionally add properties only if they exist and are not empty
 */
const getPropertiesIfNotEmpty = (props: any) => {
    return props && Object.keys(props).length > 0 ? { properties: props } : {}
}

/**
 * Transform tool input metrics to ExperimentMetric format for API
 */
const transformMetricToApi = (metric: any): z.infer<typeof ExperimentMetricSchema> => {
    const uuid = uuidv4()
    const base = {
        kind: 'ExperimentMetric' as const,
        uuid,
        name: metric.name,
    }

    switch (metric.metric_type) {
        case 'mean':
            return {
                ...base,
                metric_type: 'mean',
                source: {
                    kind: 'EventsNode',
                    event: metric.event_name,
                    ...getPropertiesIfNotEmpty(metric.properties),
                },
            }

        case 'funnel':
            return {
                ...base,
                metric_type: 'funnel',
                series: (metric.funnel_steps || [metric.event_name]).map((event: string) => ({
                    kind: 'EventsNode',
                    event,
                    ...getPropertiesIfNotEmpty(metric.properties),
                })),
            }

        case 'ratio': {
            const numeratorProps = metric.properties?.numerator || metric.properties
            const denominatorProps = metric.properties?.denominator || metric.properties

            return {
                ...base,
                metric_type: 'ratio',
                numerator: {
                    kind: 'EventsNode',
                    event: metric.event_name,
                    ...getPropertiesIfNotEmpty(numeratorProps),
                },
                denominator: {
                    kind: 'EventsNode',
                    event: metric.properties?.denominator_event || metric.event_name,
                    ...getPropertiesIfNotEmpty(denominatorProps),
                },
            }
        }

        default:
            throw new Error(`Unknown metric type: ${metric.metric_type}`)
    }
}

/**
 * Transform tool input to API payload format
 * This bridges the gap between user-friendly input and PostHog API requirements
 */
export const ExperimentCreatePayloadSchema = ToolExperimentCreateSchema.transform((input) => {
    // Transform metrics with proper UUIDs
    const primaryMetrics = input.primary_metrics?.map(transformMetricToApi) || []
    const secondaryMetrics = input.secondary_metrics?.map(transformMetricToApi) || []

    return {
        // Core fields
        name: input.name,
        description: input.description || null,
        feature_flag_key: input.feature_flag_key, // Maps to get_feature_flag_key in serializer
        type: input.type || 'product',

        // Metrics - ensure arrays are never null, always empty arrays when no metrics
        metrics: primaryMetrics,
        metrics_secondary: secondaryMetrics,

        // Metrics UUIDs for ordering - ensure arrays are never null
        primary_metrics_ordered_uuids: primaryMetrics.map((m) => m.uuid),
        secondary_metrics_ordered_uuids: secondaryMetrics.map((m) => m.uuid),

        // Legacy fields still required by API
        filters: {}, // Legacy but still in model
        secondary_metrics: secondaryMetrics, // Use the same array as metrics_secondary
        saved_metrics_ids: [], // Empty array for saved metrics

        // Parameters with variants
        parameters: {
            feature_flag_variants: input.variants || [
                { key: 'control', name: 'Control', rollout_percentage: 50 },
                { key: 'test', name: 'Test', rollout_percentage: 50 },
            ],
            minimum_detectable_effect: input.minimum_detectable_effect || 30,
        },

        // Exposure criteria
        exposure_criteria: input.filter_test_accounts
            ? {
                  filterTestAccounts: input.filter_test_accounts,
              }
            : null,

        // Stats config (empty, will be filled by backend)
        stats_config: {},

        // State fields
        start_date: input.draft === false ? new Date().toISOString() : null,
        end_date: null,
        archived: false,
        deleted: false,

        // Optional holdout
        holdout_id: input.holdout_id || null,
    }
}).pipe(ExperimentApiPayloadSchema)

export type ExperimentCreatePayload = z.output<typeof ExperimentCreatePayloadSchema>

/**
 * Transform user-friendly update input to API payload format for experiment updates
 * This handles partial updates with the same transformation patterns as creation
 */
export const ExperimentUpdateTransformSchema = ToolExperimentUpdateInputSchema.transform(
    (input) => {
        const updatePayload: Record<string, any> = {}

        // Basic fields - direct mapping
        if (input.name !== undefined) {
            updatePayload.name = input.name
        }
        if (input.description !== undefined) {
            updatePayload.description = input.description
        }

        // Transform metrics if provided
        if (input.primary_metrics !== undefined) {
            updatePayload.metrics = input.primary_metrics.map(transformMetricToApi)
            updatePayload.primary_metrics_ordered_uuids = updatePayload.metrics.map(
                (m: any) => m.uuid!
            )
        }

        if (input.secondary_metrics !== undefined) {
            updatePayload.metrics_secondary = input.secondary_metrics.map(transformMetricToApi)
            updatePayload.secondary_metrics_ordered_uuids = updatePayload.metrics_secondary.map(
                (m: any) => m.uuid!
            )
        }

        // Transform minimum detectable effect into parameters
        if (input.minimum_detectable_effect !== undefined) {
            updatePayload.parameters = {
                ...updatePayload.parameters,
                minimum_detectable_effect: input.minimum_detectable_effect,
            }
        }

        // Handle experiment state management
        if (input.launch === true) {
            updatePayload.start_date = new Date().toISOString()
        }

        if (input.conclude !== undefined) {
            updatePayload.conclusion = input.conclude
            updatePayload.end_date = new Date().toISOString()
            if (input.conclusion_comment !== undefined) {
                updatePayload.conclusion_comment = input.conclusion_comment
            }
        }

        if (input.restart === true) {
            updatePayload.end_date = null
            updatePayload.conclusion = null
            updatePayload.conclusion_comment = null
        }

        if (input.archive !== undefined) {
            updatePayload.archived = input.archive
        }

        return updatePayload
    }
).pipe(ExperimentUpdateApiPayloadSchema)

export type ExperimentUpdateTransform = z.output<typeof ExperimentUpdateTransformSchema>

/**
 * This is the schema for the experiment exposure query.
 * It references the ExperimentExposureQuery type from
 * @posthog/frontend/src/queries/schema/schema-general.ts
 */
export const ExperimentExposureQuerySchema = z.object({
    kind: z.literal('ExperimentExposureQuery'),
    experiment_id: z.number(),
    experiment_name: z.string(),
    exposure_criteria: ExperimentExposureCriteriaSchema.nullish(),
    feature_flag: FeatureFlagSchema.optional(),
    start_date: z.string().nullish(),
    end_date: z.string().nullish(),
    holdout: z.any().optional(),
})

export type ExperimentExposureQuery = z.infer<typeof ExperimentExposureQuerySchema>

export const ExperimentExposureTimeSeriesSchema = z.object({
    variant: z.string(),
    days: z.array(z.string()),
    exposure_counts: z.array(z.number()),
})

export const ExperimentExposureQueryResponseSchema = z.object({
    kind: z.literal('ExperimentExposureQuery'), // API returns the query kind, not a response kind
    timeseries: z.array(ExperimentExposureTimeSeriesSchema),
    total_exposures: z.record(z.string(), z.number()),
    date_range: z.object({
        date_from: z.string(),
        date_to: z.string().nullable(), // API can return null for date_to
    }),
})

export type ExperimentExposureQueryResponse = z.infer<typeof ExperimentExposureQueryResponseSchema>

export const ExperimentResultsResponseSchema = z
    .object({
        experiment: ExperimentSchema.pick({
            id: true,
            name: true,
            description: true,
            feature_flag_key: true,
            start_date: true,
            end_date: true,
            metrics: true,
            metrics_secondary: true,
            parameters: true, // Pick parameters to extract variants
        }).transform((data) => ({
            id: data.id,
            name: data.name,
            description: data.description,
            feature_flag_key: data.feature_flag_key,
            metrics: data.metrics,
            metrics_secondary: data.metrics_secondary,
            start_date: data.start_date,
            end_date: data.end_date,
            status: data.start_date ? (data.end_date ? 'completed' : 'running') : 'draft',
            variants: data.parameters?.feature_flag_variants || [],
        })),
        exposures: ExperimentExposureQueryResponseSchema,
        primaryMetricsResults: z.array(z.any()),
        secondaryMetricsResults: z.array(z.any()),
    })
    .transform(({ experiment, exposures, primaryMetricsResults, secondaryMetricsResults }) => {
        return {
            experiment,
            exposures,
            metrics: {
                primary: {
                    count: primaryMetricsResults.length,
                    results: primaryMetricsResults
                        .map((result, index) => ({
                            index,
                            data: result,
                        }))
                        .filter((item) => item.data !== null),
                },
                secondary: {
                    count: secondaryMetricsResults.length,
                    results: secondaryMetricsResults
                        .map((result, index) => ({
                            index,
                            data: result,
                        }))
                        .filter((item) => item.data !== null),
                },
            },
        }
    })

/**
 * Schema for updating existing experiments
 * All fields are optional to support partial updates
 */
export const ExperimentUpdatePayloadSchema = z
    .object({
        name: z.string().optional(),
        description: z.string().nullish(),
        start_date: z.string().nullish(),
        end_date: z.string().nullish(),

        // Parameters
        parameters: z
            .object({
                feature_flag_variants: z
                    .array(
                        z.object({
                            key: z.string(),
                            name: z.string().optional(),
                            rollout_percentage: z.number(),
                        })
                    )
                    .optional(),
                minimum_detectable_effect: z.number().nullish(),
                recommended_running_time: z.number().nullish(),
                recommended_sample_size: z.number().nullish(),
                variant_screenshot_media_ids: z.record(z.array(z.string())).optional(),
            })
            .optional(),

        // Metrics
        metrics: z.array(ExperimentMetricSchema).optional(),
        metrics_secondary: z.array(ExperimentMetricSchema).optional(),
        primary_metrics_ordered_uuids: z.array(z.string()).nullish(),
        secondary_metrics_ordered_uuids: z.array(z.string()).nullish(),

        // State management
        archived: z.boolean().optional(),
        conclusion: z.enum(ExperimentConclusion).nullish(),
        conclusion_comment: z.string().nullish(),

        // Configuration
        exposure_criteria: ExperimentExposureCriteriaSchema.optional(),
        saved_metrics_ids: z.array(z.any()).nullish(),
        stats_config: z.any().optional(),
    })
    .strict()

export type ExperimentUpdatePayload = z.infer<typeof ExperimentUpdatePayloadSchema>
