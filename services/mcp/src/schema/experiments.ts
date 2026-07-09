import { z } from 'zod'

const ExperimentType = ['web', 'product'] as const

const ExperimentConclusion = ['won', 'lost', 'inconclusive', 'stopped_early', 'invalid'] as const

// The flag's native variant shape (filters.multivariate.variants). This is the source
// of truth for an experiment's variants — the deprecated parameters.feature_flag_variants
// projection just echoes it. looseObject so unknown filter/variant keys survive parsing:
// the exposure query forwards the whole feature_flag object to the backend, so narrowing
// filters here would strip groups/payloads/etc. before the query is sent.
const FeatureFlagVariantSchema = z.looseObject({
    key: z.string(),
    name: z.string().nullish(),
    rollout_percentage: z.number().nullish(),
})

const FeatureFlagFiltersSchema = z.looseObject({
    multivariate: z
        .looseObject({
            variants: z.array(FeatureFlagVariantSchema).nullish(),
        })
        .nullish(),
})

const FeatureFlagSchema = z.object({
    id: z.number(),
    key: z.string(),
    name: z.string(),
    description: z.string().nullish(),
    filters: FeatureFlagFiltersSchema.nullish(),
    active: z.boolean(),
    tags: z.array(z.string()).optional(),
    updated_at: z.string().nullish(),
})

const ExperimentEventExposureConfigSchema = z.object({
    kind: z.literal('ExperimentEventExposureConfig'),
    event: z.string(),
    properties: z.array(z.any()),
})

// Action-based exposure: the experiment counts a user as exposed when they match a
// PostHog action (kind 'ActionsNode', identified by numeric `id`) rather than a custom
// event. The backend resolves the action by id, so id + properties round-trip faithfully
// into the ExperimentExposureQuery.
const ExperimentActionExposureConfigSchema = z.object({
    kind: z.literal('ActionsNode'),
    id: z.number(),
    properties: z.array(z.any()).optional(),
})

const ExperimentExposureConfigSchema = z.union([
    ExperimentEventExposureConfigSchema,
    ExperimentActionExposureConfigSchema,
])

const ExperimentExposureCriteriaSchema = z.object({
    filterTestAccounts: z.boolean().optional(),
    exposure_config: ExperimentExposureConfigSchema.optional(),
    multiple_variant_handling: z.enum(['exclude', 'first_seen']).optional(),
})

/**
 * One entry of `experiment.saved_metrics` — a junction row attaching a shared
 * saved metric to an experiment. Mirrors `ExperimentToSavedMetricSerializer` on
 * the backend. Kept loose (looseObject so extra fields survive, nullish on
 * every field) so a malformed row doesn't fail parsing of the whole experiment;
 * `buildMetricEntries` does the strict filtering. Tightening this catches
 * backend field renames at the type boundary instead of silently nulling out
 * shared-row fields.
 */
export const SavedMetricAttachmentSchema = z.looseObject({
    saved_metric: z.number().nullish(),
    name: z.string().nullish(),
    metadata: z
        .looseObject({
            type: z.string().nullish(),
        })
        .nullish(),
    query: z.unknown(),
})

export type SavedMetricAttachment = z.infer<typeof SavedMetricAttachmentSchema>

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
    saved_metrics: z.array(SavedMetricAttachmentSchema).nullish(),
    saved_metrics_ids: z.array(z.any()).nullable(),
    parameters: z
        .object({
            feature_flag_variants: z
                .array(
                    z.object({
                        key: z.string(),
                        name: z.string().nullish(),
                        rollout_percentage: z.number().nullish(),
                        split_percent: z.number().nullish(),
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

export type MetricSummary = {
    uuid: string | null
    name: string | null
    metric_type: string | null
    goal: string | null
    source: 'inline' | 'shared'
    saved_metric_id: number | null
    saved_metric_name: string | null
}

export type ResolvedMetricEntry = {
    /** metric is forwarded to the ExperimentQuery body but not read by MCP. */
    metric: unknown
    summary: MetricSummary
}

export type ExperimentMetricResultRow = {
    index: number
    metric: MetricSummary
    data: unknown
}

export interface ExperimentResultsSummary {
    experiment: {
        id: number
        name: string
        description?: string | null | undefined
        feature_flag_key: string
        metrics?: unknown[] | null | undefined
        metrics_secondary?: unknown[] | null | undefined
        saved_metrics?: unknown[] | null | undefined
        start_date?: string | null | undefined
        end_date?: string | null | undefined
        status: 'draft' | 'running' | 'completed'
        variants: Array<{
            key: string
            name?: string | null | undefined
            rollout_percentage?: number | null | undefined
            split_percent?: number | null | undefined
        }>
    }
    exposures: ExperimentExposureQueryResponse
    metrics: {
        primary: {
            count: number
            results: ExperimentMetricResultRow[]
        }
        secondary: {
            count: number
            results: ExperimentMetricResultRow[]
        }
    }
}

function toMetricSummary(
    metric: unknown,
    source: 'inline' | 'shared',
    saved: { id: number | null; name: string | null } = { id: null, name: null }
): MetricSummary {
    const m = (metric ?? {}) as Record<string, unknown>
    const queryName = typeof m.name === 'string' ? m.name : null
    // For shared rows, the saved metric's label is what users see in the UI, the
    // inner query.name is internal and often unset or drifted
    const name = source === 'shared' ? (saved.name ?? queryName) : queryName
    return {
        uuid: typeof m.uuid === 'string' ? m.uuid : null,
        name,
        metric_type: typeof m.metric_type === 'string' ? m.metric_type : null,
        goal: typeof m.goal === 'string' ? m.goal : null,
        source,
        saved_metric_id: saved.id,
        saved_metric_name: saved.name,
    }
}

/**
 * Build the per-position metric entries for a primary/secondary slot, merging the
 * inline metrics on the experiment with the shared metrics (saved_metrics), and
 * ordering them by `*_metrics_ordered_uuids` so the result rows match what users
 * see in the UI. Each entry tracks its source so each result row can be
 * self-describing.
 */
export function buildMetricEntries(experiment: Experiment, slot: 'primary' | 'secondary'): ResolvedMetricEntry[] {
    const inline = (slot === 'primary' ? experiment.metrics : experiment.metrics_secondary) ?? []
    const shared = (experiment.saved_metrics ?? []).filter((sm) => sm.metadata?.type === slot)
    const entries: ResolvedMetricEntry[] = [
        ...inline.map((metric) => ({ metric: metric as unknown, summary: toMetricSummary(metric, 'inline') })),
        ...shared.map((sm) => ({
            metric: sm.query,
            summary: toMetricSummary(sm.query, 'shared', {
                id: typeof sm.saved_metric === 'number' ? sm.saved_metric : null,
                name: typeof sm.name === 'string' ? sm.name : null,
            }),
        })),
    ]

    // Sort by position in *_metrics_ordered_uuids so result rows match the UI.
    // Entries whose uuid isn't listed (legacy or stale ordering) keep their
    // insertion order at the end thanks to stable Array.prototype.sort.
    const orderedUuids =
        (slot === 'primary' ? experiment.primary_metrics_ordered_uuids : experiment.secondary_metrics_ordered_uuids) ??
        []
    if (orderedUuids.length === 0) {
        return entries
    }
    const positionByUuid = new Map<string, number>()
    orderedUuids.forEach((uuid, i) => positionByUuid.set(uuid, i))
    const fallbackPosition = orderedUuids.length
    const position = (entry: ResolvedMetricEntry): number =>
        entry.summary.uuid ? (positionByUuid.get(entry.summary.uuid) ?? fallbackPosition) : fallbackPosition
    return [...entries].sort((a, b) => position(a) - position(b))
}

/**
 * Strip UI-only bulk fields from a query response. The compiled SQL bodies and the
 * per-step session samples can together account for ~90% of the payload. None of it
 * is usable by an MCP caller — `step_sessions` powers the frontend's funnel step-bar
 * "view sessions" linkbacks, `insight` is the rendered visualization payload for
 * the legacy trends/funnels charts, and anyone debugging a compiled query should
 * hit the dedicated query API directly. Statistical fields (sum, sum_squares,
 * step_counts, number_of_samples, credible_intervals, etc.) are left untouched,
 * including per-breakdown statistics in `breakdown_results` — the sessions inside
 * each breakdown entry are stripped, but the breakdown stats themselves are kept
 * because they are real per-segment analysis data.
 */
function stripBulkFields(data: unknown): unknown {
    if (data === null || typeof data !== 'object') {
        return data
    }
    const {
        clickhouse_sql: _omitSql,
        hogql: _omitHogql,
        insight: _omitInsight,
        baseline: rawBaseline,
        variant_results: rawVariantResults,
        breakdown_results: rawBreakdownResults,
        ...rest
    } = data as Record<string, unknown>

    const stripVariantBulk = (variant: unknown): unknown => {
        if (variant === null || typeof variant !== 'object') {
            return variant
        }
        const { step_sessions: _omitStepSessions, ...variantRest } = variant as Record<string, unknown>
        return variantRest
    }

    const stripBreakdownBulk = (entry: unknown): unknown => {
        if (entry === null || typeof entry !== 'object') {
            return entry
        }
        const { baseline: bdBaseline, variants: bdVariants, ...bdRest } = entry as Record<string, unknown>
        return {
            ...bdRest,
            ...(bdBaseline !== undefined ? { baseline: stripVariantBulk(bdBaseline) } : {}),
            ...(bdVariants !== undefined
                ? {
                      variants: Array.isArray(bdVariants) ? bdVariants.map(stripVariantBulk) : bdVariants,
                  }
                : {}),
        }
    }

    return {
        ...rest,
        ...(rawBaseline !== undefined ? { baseline: stripVariantBulk(rawBaseline) } : {}),
        ...(rawVariantResults !== undefined
            ? {
                  variant_results: Array.isArray(rawVariantResults)
                      ? rawVariantResults.map(stripVariantBulk)
                      : rawVariantResults,
              }
            : {}),
        ...(rawBreakdownResults !== undefined
            ? {
                  breakdown_results: Array.isArray(rawBreakdownResults)
                      ? rawBreakdownResults.map(stripBreakdownBulk)
                      : rawBreakdownResults,
              }
            : {}),
    }
}

export function transformExperimentResults(input: {
    experiment: Experiment
    exposures: ExperimentExposureQueryResponse
    primaryMetricEntries: ResolvedMetricEntry[]
    secondaryMetricEntries: ResolvedMetricEntry[]
    primaryMetricsResults: unknown[]
    secondaryMetricsResults: unknown[]
}): ExperimentResultsSummary {
    const {
        experiment,
        exposures,
        primaryMetricEntries,
        secondaryMetricEntries,
        primaryMetricsResults,
        secondaryMetricsResults,
    } = input

    const transformedExperiment = {
        id: experiment.id,
        name: experiment.name,
        description: experiment.description,
        feature_flag_key: experiment.feature_flag_key,
        metrics: experiment.metrics,
        metrics_secondary: experiment.metrics_secondary,
        saved_metrics: experiment.saved_metrics,
        start_date: experiment.start_date,
        end_date: experiment.end_date,
        status: (experiment.start_date ? (experiment.end_date ? 'completed' : 'running') : 'draft') as
            | 'draft'
            | 'running'
            | 'completed',
        variants: experiment.feature_flag?.filters?.multivariate?.variants ?? [],
    }

    const buildRows = (
        results: unknown[],
        entries: ResolvedMetricEntry[]
    ): { count: number; results: ExperimentMetricResultRow[] } => {
        if (results.length !== entries.length) {
            // Defensive throwing since the two arrays are paired by index, one result per entry
            throw new Error(
                `experiment-results-get (experiment ${experiment.id}): result/entry length mismatch (${results.length} results, ${entries.length} entries) — this should not happen, please report.`
            )
        }
        // Failed metric queries surface as `data: null` so callers can see "metric N
        // exists and failed" instead of having the row erased and subsequent metric
        // positions shift relative to *_metrics_ordered_uuids.
        return {
            count: results.length,
            results: results.map((result, index) => ({
                index,
                metric: entries[index]!.summary,
                data: stripBulkFields(result),
            })),
        }
    }

    return {
        experiment: transformedExperiment,
        exposures,
        metrics: {
            primary: buildRows(primaryMetricsResults, primaryMetricEntries),
            secondary: buildRows(secondaryMetricsResults, secondaryMetricEntries),
        },
    }
}
