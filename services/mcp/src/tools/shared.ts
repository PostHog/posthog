type QueryKind =
    | 'TrendsQuery'
    | 'FunnelsQuery'
    | 'RetentionQuery'
    | 'LifecycleQuery'
    | 'StickinessQuery'
    | 'PathsQuery'
    | 'HogQLQuery'
    | 'InsightVizNode'
    | 'DataVisualizationNode'
    | string

interface QueryInfo {
    visualization: 'trends' | 'funnel' | 'retention' | 'lifecycle' | 'stickiness' | 'paths' | 'table'
    /** The inner query kind (e.g., TrendsQuery inside InsightVizNode) */
    innerKind: QueryKind
    /** The inner query object for insight queries */
    innerQuery?: Record<string, unknown>
}

/** Insight query kinds whose results are a raw array consumed directly by the chart visualizers. */
const SOURCE_VISUALIZATIONS: Record<string, QueryInfo['visualization']> = {
    TrendsQuery: 'trends',
    FunnelsQuery: 'funnel',
    RetentionQuery: 'retention',
    LifecycleQuery: 'lifecycle',
    StickinessQuery: 'stickiness',
    PathsQuery: 'paths',
}

/**
 * Analyze the query to determine visualization type and extract inner query info.
 */
export function analyzeQuery(query: unknown): QueryInfo {
    if (!query || typeof query !== 'object') {
        return { visualization: 'table', innerKind: 'unknown' }
    }

    const q = query as Record<string, unknown>

    // Direct insight queries
    const visualization = typeof q.kind === 'string' ? SOURCE_VISUALIZATIONS[q.kind] : undefined
    if (visualization) {
        return { visualization, innerKind: q.kind as string, innerQuery: q }
    }
    if (q.kind === 'HogQLQuery') {
        return { visualization: 'table', innerKind: 'HogQLQuery' }
    }

    // InsightVizNode wraps insight queries
    if (q.kind === 'InsightVizNode' && q.source && typeof q.source === 'object') {
        const source = q.source as Record<string, unknown>
        const sourceVisualization = typeof source.kind === 'string' ? SOURCE_VISUALIZATIONS[source.kind] : undefined
        if (sourceVisualization) {
            return { visualization: sourceVisualization, innerKind: source.kind as string, innerQuery: source }
        }
    }

    // DataVisualizationNode wraps HogQL queries for custom visualizations
    if (q.kind === 'DataVisualizationNode' && q.source && typeof q.source === 'object') {
        return { visualization: 'table', innerKind: 'HogQLQuery' }
    }

    return { visualization: 'table', innerKind: String(q.kind || 'unknown') }
}
