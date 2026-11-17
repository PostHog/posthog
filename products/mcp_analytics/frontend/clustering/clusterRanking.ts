import type { MCPIntentClusterApi, MCPIntentClusterLongTailApi } from '../generated/api.schemas'

// A cluster with fewer sessions is one or two agents repeating themselves, so its routing
// shape says little about the tools. It still ranks in the list but stays out of the KPIs.
export const MIN_KPI_SESSIONS = 5

export const TOP_TOOLS_PER_CLUSTER = 3

export function countsTowardKpis(cluster: Pick<MCPIntentClusterApi, 'session_count'>): boolean {
    return cluster.session_count >= MIN_KPI_SESSIONS
}

export function topToolNames(
    cluster: Pick<MCPIntentClusterApi, 'tool_distribution'>,
    limit = TOP_TOOLS_PER_CLUSTER
): string[] {
    return [...cluster.tool_distribution]
        .sort((a, b) => b.count - a.count)
        .slice(0, limit)
        .map((entry) => entry.tool)
}

// Labels come back empty when access control hides intent text. Keyed on the cluster id
// rather than list position so the fallback name survives a re-sort.
export function clusterLabel(cluster: Pick<MCPIntentClusterApi, 'id' | 'label'>): string {
    if (!cluster.label.trim()) {
        return `Intent group ${cluster.id}`
    }
    return cluster.label
}

export function longTailLabel(longTail: Pick<MCPIntentClusterLongTailApi, 'intent_count'>): string {
    const n = longTail.intent_count
    return `Long tail: ${n.toLocaleString()} one-off intent${n === 1 ? '' : 's'}`
}

export function formatErrorRate(errorRatePct: number): string {
    return `${errorRatePct.toFixed(1)}%`
}
