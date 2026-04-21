import { z } from 'zod'

const ExperimentType = ['web', 'product'] as const

const ExperimentConclusion = ['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'] as const

const FeatureFlagSchema = z.object({
    id: z.number(),
    key: z.string(),
    name: z.string(),
    description: z.string().nullish(),
    filters: z.any().nullish(),
    active: z.boolean(),
    tags: z.array(z.string()).optional(),
    updated_at: z.string().nullish(),
})

const ExperimentEventExposureConfigSchema = z.object({
    kind: z.literal('ExperimentEventExposureConfig'),
    event: z.string(),
    properties: z.array(z.any()),
})

const ExperimentExposureCriteriaSchema = z.object({
    filterTestAccounts: z.boolean().optional(),
    exposure_config: ExperimentEventExposureConfigSchema.optional(),
    multiple_variant_handling: z.enum(['exclude', 'first_seen']).optional(),
})

/**
 * Hand-written Experiment schema used by the results tool's API client methods.
 * The codegen tools use Schemas.Experiment from the generated OpenAPI types instead.
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
    metrics: z.array(z.any()).nullish(),
    metrics_secondary: z.array(z.any()).nullish(),
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
    scheduling_config: z.any().optional(),
    conclusion: z.enum(ExperimentConclusion).nullish(),
    conclusion_comment: z.string().nullish(),
    primary_metrics_ordered_uuids: z.array(z.string()).nullish(),
    secondary_metrics_ordered_uuids: z.array(z.string()).nullish(),
})

export type Experiment = z.infer<typeof ExperimentSchema>

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
    kind: z.literal('ExperimentExposureQuery'),
    timeseries: z.array(ExperimentExposureTimeSeriesSchema),
    total_exposures: z.record(z.string(), z.number()),
    date_range: z.object({
        date_from: z.string(),
        date_to: z.string().nullable(),
    }),
})

export type ExperimentExposureQueryResponse = z.infer<typeof ExperimentExposureQueryResponseSchema>

export interface ExperimentResultsSummary {
    experiment: {
        id: number
        name: string
        description?: string | null | undefined
        feature_flag_key: string
        metrics?: unknown[] | null | undefined
        metrics_secondary?: unknown[] | null | undefined
        start_date?: string | null | undefined
        end_date?: string | null | undefined
        status: 'draft' | 'running' | 'completed'
        variants: Array<{
            key: string
            name?: string | null | undefined
            rollout_percentage?: number | null | undefined
        }>
    }
    exposures: ExperimentExposureQueryResponse
    metrics: {
        primary: {
            count: number
            results: Array<{ index: number; data: unknown }>
        }
        secondary: {
            count: number
            results: Array<{ index: number; data: unknown }>
        }
    }
}

export function transformExperimentResults(input: {
    experiment: Experiment
    exposures: ExperimentExposureQueryResponse
    primaryMetricsResults: unknown[]
    secondaryMetricsResults: unknown[]
}): ExperimentResultsSummary {
    const { experiment, exposures, primaryMetricsResults, secondaryMetricsResults } = input

    const transformedExperiment = {
        id: experiment.id,
        name: experiment.name,
        description: experiment.description,
        feature_flag_key: experiment.feature_flag_key,
        metrics: experiment.metrics,
        metrics_secondary: experiment.metrics_secondary,
        start_date: experiment.start_date,
        end_date: experiment.end_date,
        status: (experiment.start_date ? (experiment.end_date ? 'completed' : 'running') : 'draft') as
            | 'draft'
            | 'running'
            | 'completed',
        variants: experiment.parameters?.feature_flag_variants || [],
    }

    return {
        experiment: transformedExperiment,
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
}
