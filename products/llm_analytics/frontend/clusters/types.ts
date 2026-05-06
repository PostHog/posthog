import { dayjs } from 'lib/dayjs'

// Whether clustering is at trace level, individual generation level, or evaluation level
export type ClusteringLevel = 'trace' | 'generation' | 'evaluation'

/**
 * Extract day bounds from a clustering run ID for efficient timestamp filtering.
 * Run IDs are formatted as `<team_id>_<level>_<YYYYMMDD>_<HHMMSS>` where level is
 * "trace", "generation", or "evaluation".
 * Returns start and end of the day to ensure we capture the event.
 * Falls back to last 7 days if parsing fails.
 */
export function getLevelFromRunId(runId: string): ClusteringLevel {
    const parts = runId.split('_')
    // Run ID format: <team_id>_<level>_<YYYYMMDD>_<HHMMSS>
    if (parts.length >= 2 && (parts[1] === 'trace' || parts[1] === 'generation' || parts[1] === 'evaluation')) {
        return parts[1]
    }
    return 'trace' // Default to trace for backwards compatibility
}

export function getTimestampBoundsFromRunId(runId: string): { dayStart: string; dayEnd: string } {
    const parts = runId.split('_')
    const dateFormat = 'YYYY-MM-DD HH:mm:ss'

    if (parts.length >= 4) {
        const dateStr = parts[2]
        const timeStr = parts[3]

        const parsed = dayjs.utc(`${dateStr}_${timeStr}`, 'YYYYMMDD_HHmmss')
        if (parsed.isValid()) {
            return {
                dayStart: parsed.startOf('day').utc().format(dateFormat),
                dayEnd: parsed.endOf('day').utc().format(dateFormat),
            }
        }
    }

    return {
        dayStart: dayjs().subtract(7, 'day').startOf('day').utc().format(dateFormat),
        dayEnd: dayjs().endOf('day').utc().format(dateFormat),
    }
}

// Cluster item info from the $ai_trace_clusters or $ai_generation_clusters event
export interface ClusterItemInfo {
    distance_to_centroid: number
    rank: number
    x: number // UMAP 2D x coordinate for scatter plot
    y: number // UMAP 2D y coordinate for scatter plot
    timestamp: string // First event timestamp of the trace (ISO format) for efficient linking
    trace_id: string // Always set - the trace ID (or parent trace for generations)
    generation_id?: string // Only set for generation-level clustering
}

// Cluster data structure from the $ai_clusters property
export interface Cluster {
    cluster_id: number
    size: number
    title: string
    description: string
    traces: Record<string, ClusterItemInfo>
    centroid: number[] // 384-dim vector, not used in UI but present in data
    centroid_x: number // UMAP 2D x coordinate for scatter plot
    centroid_y: number // UMAP 2D y coordinate for scatter plot
    // Pre-computed aggregate metrics baked into the event by the backend. Evaluation
    // clusters always ship with this populated (via ClusterAggregateMetrics); trace and
    // generation clusters may or may not, depending on whether the aggregates activity
    // succeeded during that run. The frontend uses this directly when present
    // instead of recomputing via clusterMetricsLoader.
    metrics?: ClusterMetrics
}

// Parameters used for a clustering run
export interface ClusteringParams {
    clustering_method: string // "hdbscan" or "kmeans"
    clustering_method_params: Record<string, unknown> // Method-specific params
    embedding_normalization: string // "none" or "l2"
    dimensionality_reduction_method: string // "none", "umap", or "pca"
    dimensionality_reduction_ndims: number // Target dimensions
    visualization_method: string // "umap", "pca", or "tsne"
    max_samples: number // Max traces to sample
}

// Full clustering run event data
export interface ClusteringRun {
    runId: string // $ai_clustering_run_id
    windowStart: string // $ai_window_start
    windowEnd: string // $ai_window_end
    totalItemsAnalyzed: number // Traces or generations depending on level
    clusters: Cluster[]
    timestamp: string // Event timestamp
    clusteringParams?: ClusteringParams // Parameters used for this run
    level?: ClusteringLevel // $ai_clustering_level - "trace" or "generation"
}

// Run option for the dropdown selector
export interface ClusteringRunOption {
    runId: string
    windowEnd: string
    label: string // Formatted date for display
}

// Summary from $ai_trace_summary or $ai_generation_summary events — or, for
// evaluation-level clusters, a shim of the underlying $ai_evaluation event
// (evaluator name, verdict, reasoning, linked generation id) rendered into the
// same interface so the list component doesn't need a separate prop.
export interface TraceSummary {
    traceId: string // Always set - the trace ID (or parent trace for generations / eval's $ai_trace_id)
    generationId?: string // Set for generation-level summaries; for eval, the linked generation uuid
    title: string
    flowDiagram: string
    bullets: string
    interestingNotes: string
    timestamp: string
    // Evaluation-only fields (empty/undefined for trace/generation summaries)
    evaluationVerdict?: 'pass' | 'fail' | 'n/a' | 'unknown'
    evaluationReasoning?: string
    evaluationRuntime?: string
}

// Clustering job configuration
export interface ClusteringJob {
    id: number
    name: string
    analysis_level: ClusteringLevel
    event_filters: Record<string, unknown>[]
    enabled: boolean
    created_at: string
    updated_at: string
}

/**
 * Extract job_id from a clustering run ID.
 * Run ID format: <team_id>_<level>_<YYYYMMDD>_<HHMMSS>[_<job_id>][_<label>]
 * Job IDs are UUIDs (e.g. 019cb7f3-a126-7809-bffc-7f13bffe1325).
 * We match the UUID pattern in the suffix to avoid capturing a trailing run_label.
 */
const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i

export function getJobIdFromRunId(runId: string): string | null {
    const parts = runId.split('_')
    // The first 4 parts are always: teamId, level, YYYYMMDD, HHMMSS
    if (parts.length >= 5) {
        const suffix = parts.slice(4).join('_')
        const match = UUID_PATTERN.exec(suffix)
        if (match) {
            return match[0]
        }
    }
    return null
}

// Aggregated metrics for a cluster (averages across all items in the cluster)
export interface ClusterMetrics {
    avgCost: number | null // Average cost in USD
    avgLatency: number | null // Average latency in seconds
    avgTokens: number | null // Average total tokens (input + output)
    totalCost: number | null // Total cost across all items
    errorRate: number | null // Proportion of items with errors (0-1)
    errorCount: number // Number of items with errors
    itemCount: number // Number of items with metrics data
    // Evaluation-only fields (null for trace / generation levels). Emitted by the
    // backend's ClusterAggregateMetrics for $ai_evaluation_clusters events.
    passRate?: number | null // 0-1, share of cluster evals with a "pass" verdict
    naRate?: number | null // 0-1, share of cluster evals with an "n/a" verdict
    dominantEvaluationName?: string | null // Most common evaluator name in the cluster
    dominantRuntime?: string | null // "llm_judge" | "hog" — most common runtime
    avgJudgeCost?: number | null // Average $ai_total_cost_usd on the eval itself (llm_judge only)
}

/**
 * Parse a cluster's `metrics` dict (snake_case, emitted by the backend via
 * dataclasses.asdict) into the frontend's camelCase `ClusterMetrics` shape.
 * Returns null when the backend didn't include metrics for this cluster (e.g.
 * a trace/generation run where the aggregates activity failed).
 */
export function parseClusterMetrics(raw: unknown): ClusterMetrics | null {
    if (!raw || typeof raw !== 'object') {
        return null
    }
    const r = raw as Record<string, unknown>
    return {
        avgCost: (r.avg_cost as number | null) ?? null,
        avgLatency: (r.avg_latency as number | null) ?? null,
        avgTokens: (r.avg_tokens as number | null) ?? null,
        totalCost: (r.total_cost as number | null) ?? null,
        errorRate: (r.error_rate as number | null) ?? null,
        errorCount: (r.error_count as number) ?? 0,
        itemCount: (r.item_count as number) ?? 0,
        passRate: (r.pass_rate as number | null) ?? null,
        naRate: (r.na_rate as number | null) ?? null,
        dominantEvaluationName: (r.dominant_evaluation_name as string | null) ?? null,
        dominantRuntime: (r.dominant_runtime as string | null) ?? null,
        avgJudgeCost: (r.avg_judge_cost as number | null) ?? null,
    }
}
