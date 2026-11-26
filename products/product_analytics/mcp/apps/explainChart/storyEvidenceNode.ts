export function storyEvidenceNode(query: Record<string, unknown>): Record<string, unknown> {
    const kind = typeof query.kind === 'string' ? query.kind : 'TrendsQuery'
    if (kind === 'HogQLQuery') {
        return { kind: 'DataVisualizationNode', source: query }
    }
    return kind.endsWith('Node') ? query : { kind: 'InsightVizNode', source: { ...query, kind } }
}
