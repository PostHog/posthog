// Noise/outlier cluster ID from HDBSCAN
export const NOISE_CLUSTER_ID = -1

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

// Full clustering run event data
export interface ClusteringRun {
    runId: string // $ai_clustering_run_id
    windowStart: string // $ai_window_start
    windowEnd: string // $ai_window_end
    totalTracesAnalyzed: number
    clusters: Cluster[]
    timestamp: string // Event timestamp
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
