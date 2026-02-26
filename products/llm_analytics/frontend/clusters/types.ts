import { dayjs } from 'lib/dayjs'

// Whether clustering is at trace level or individual generation level
export type ClusteringLevel = 'trace' | 'generation'

/**
 * Extract day bounds from a clustering run ID for efficient timestamp filtering.
 * Run IDs are formatted as `<team_id>_<level>_<YYYYMMDD>_<HHMMSS>` where level is "trace" or "generation".
 * Returns start and end of the day to ensure we capture the event.
 * Falls back to last 7 days if parsing fails.
 */
export function getLevelFromRunId(runId: string): ClusteringLevel {
    const parts = runId.split('_')
    // Run ID format: <team_id>_<level>_<YYYYMMDD>_<HHMMSS>
    if (parts.length >= 2 && (parts[1] === 'trace' || parts[1] === 'generation')) {
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

// Summary from $ai_trace_summary or $ai_generation_summary events
export interface TraceSummary {
    traceId: string // Always set - the trace ID (or parent trace for generations)
    generationId?: string // Only set for generation-level summaries
    title: string
    flowDiagram: string
    bullets: string
    interestingNotes: string
    timestamp: string
}

// Aggregated metrics for a cluster (averages across all items in the cluster)
export interface ClusterMetrics {
    avgCost: number | null // Average cost in USD
    avgLatency: number | null // Average latency in seconds
    avgTokens: number | null // Average total tokens (input + output)
    totalCost: number | null // Total cost across all items
    errorRate: number | null // Proportion of items with at least one error (0-1)
    errorCount: number // Number of items with at least one error
    itemCount: number // Number of items with metrics data
}
