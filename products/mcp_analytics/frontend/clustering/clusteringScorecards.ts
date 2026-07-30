import type { MCPIntentClusterApi } from '../generated/api.schemas'

// Routing KPIs are only meaningful when the same intent theme recurs across
// sessions — a single session touching many tools is a normal multi-step task,
// not drift. Clusters below this floor are shown in the list but excluded
// from the scorecard denominators.
export const KPI_MIN_SESSIONS = 5

function kpiEligible(clusters: readonly MCPIntentClusterApi[]): MCPIntentClusterApi[] {
    return clusters.filter((c) => c.session_count >= KPI_MIN_SESSIONS)
}

export function computeConcentratedRoutes(clusters: readonly MCPIntentClusterApi[]): {
    focused: number
    total: number
} {
    const eligible = kpiEligible(clusters)
    return {
        focused: eligible.filter((c) => (c.tool_distribution[0]?.pct ?? 0) >= 80).length,
        total: eligible.length,
    }
}

export function computeSpreadRoutes(clusters: readonly MCPIntentClusterApi[]): number {
    return kpiEligible(clusters).filter((c) => {
        const top = c.tool_distribution[0]?.pct ?? 100
        return c.tool_distribution.length >= 2 && top < 50
    }).length
}

export function computeTopErrorRoute(clusters: readonly MCPIntentClusterApi[]): MCPIntentClusterApi | null {
    const withErrors = kpiEligible(clusters).filter((c) => c.error_rate_pct > 0)
    if (withErrors.length === 0) {
        return null
    }
    // Highest traffic-weighted error count — the cluster that loses the most calls to errors.
    return [...withErrors].sort((a, b) => b.call_count * b.error_rate_pct - a.call_count * a.error_rate_pct)[0]
}
