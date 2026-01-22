import { dayjs } from 'lib/dayjs'

/**
 * Extract day bounds from a clustering run ID for efficient timestamp filtering.
 * Run IDs are formatted as `<team_id>_<YYYYMMDD>_<HHMMSS>`.
 * Returns start and end of the day to ensure we capture the event.
 * Falls back to last 7 days if parsing fails.
 */
export function getTimestampBoundsFromRunId(runId: string): { dayStart: string; dayEnd: string } {
    const parts = runId.split('_')
    // Use format compatible with ClickHouse DateTime64 comparisons
    const dateFormat = 'YYYY-MM-DD HH:mm:ss'

    if (parts.length >= 3) {
        // Parts: [team_id, YYYYMMDD, HHMMSS]
        const dateStr = parts[1]
        const timeStr = parts[2]

        // Parse YYYYMMDD_HHMMSS format as UTC (backend generates run_id using workflow.now() which is UTC)
        const parsed = dayjs.utc(`${dateStr}_${timeStr}`, 'YYYYMMDD_HHmmss')
        if (parsed.isValid()) {
            return {
                dayStart: parsed.startOf('day').utc().format(dateFormat),
                dayEnd: parsed.endOf('day').utc().format(dateFormat),
            }
        }
    }

    // Fallback to last 7 days
    return {
        dayStart: dayjs().subtract(7, 'day').startOf('day').utc().format(dateFormat),
        dayEnd: dayjs().endOf('day').utc().format(dateFormat),
    }
}

// Cluster trace info from the $ai_trace_clusters event
export interface ClusterTraceInfo {
    distance_to_centroid: number
    rank: number
    x: number // UMAP 2D x coordinate for scatter plot
    y: number // UMAP 2D y coordinate for scatter plot
    timestamp: string // First event timestamp of the trace (ISO format) for efficient linking
}

// Cluster data structure from the $ai_clusters property
export interface Cluster {
    cluster_id: number
    size: number
    title: string
    description: string
    traces: Record<string, ClusterTraceInfo>
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
    totalTracesAnalyzed: number
    clusters: Cluster[]
    timestamp: string // Event timestamp
    clusteringParams?: ClusteringParams // Parameters used for this run
}

// Run option for the dropdown selector
export interface ClusteringRunOption {
    runId: string
    windowEnd: string
    label: string // Formatted date for display
}

// Trace summary from $ai_trace_summary events
export interface TraceSummary {
    traceId: string
    title: string
    flowDiagram: string
    bullets: string
    interestingNotes: string
    timestamp: string
}
