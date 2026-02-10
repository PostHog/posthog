type QueryKind = 'TrendsQuery' | 'FunnelsQuery' | 'HogQLQuery' | 'InsightVizNode' | 'DataVisualizationNode' | string

interface QueryInfo {
    visualization: 'trends' | 'funnel' | 'table'
    /** The inner query kind (e.g., TrendsQuery inside InsightVizNode) */
    innerKind: QueryKind
    /** The inner query object for insight queries */
    innerQuery?: Record<string, unknown>
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
    if (q.kind === 'TrendsQuery') {
        return { visualization: 'trends', innerKind: 'TrendsQuery', innerQuery: q }
    }
    if (q.kind === 'FunnelsQuery') {
        return { visualization: 'funnel', innerKind: 'FunnelsQuery', innerQuery: q }
    }
    if (q.kind === 'HogQLQuery') {
        return { visualization: 'table', innerKind: 'HogQLQuery' }
    }

    // InsightVizNode wraps insight queries
    if (q.kind === 'InsightVizNode' && q.source && typeof q.source === 'object') {
        const source = q.source as Record<string, unknown>
        if (source.kind === 'TrendsQuery') {
            return { visualization: 'trends', innerKind: 'TrendsQuery', innerQuery: source }
        }
        if (source.kind === 'FunnelsQuery') {
            return { visualization: 'funnel', innerKind: 'FunnelsQuery', innerQuery: source }
        }
    }

    // DataVisualizationNode wraps HogQL queries for custom visualizations
    if (q.kind === 'DataVisualizationNode' && q.source && typeof q.source === 'object') {
        return { visualization: 'table', innerKind: 'HogQLQuery' }
    }

    return { visualization: 'table', innerKind: String(q.kind || 'unknown') }
}
