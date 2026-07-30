import type { MCPIntentClusterApi } from '../generated/api.schemas'
import {
    KPI_MIN_SESSIONS,
    computeConcentratedRoutes,
    computeSpreadRoutes,
    computeTopErrorRoute,
} from './clusteringScorecards'

function cluster(overrides: Partial<MCPIntentClusterApi>): MCPIntentClusterApi {
    return {
        id: 1,
        label: 'a cluster',
        intent_count: 2,
        session_count: KPI_MIN_SESSIONS,
        call_count: 50,
        error_count: 0,
        error_rate_pct: 0,
        routing_entropy: 0.5,
        tool_distribution: [],
        sample_intents: [],
        journey: null,
        ...overrides,
    }
}

describe('clustering scorecards', () => {
    // Regression: KPIs used to count every cluster, so 1-session clusters
    // (an agent doing a normal multi-step task) dominated "spread routes"
    // and made the drift signal always alarming.
    it('excludes clusters below the session floor from all three KPIs', () => {
        const tiny = cluster({
            id: 1,
            session_count: 1,
            error_rate_pct: 50,
            call_count: 100,
            tool_distribution: [
                { tool: 'a', count: 40, pct: 40, errors: 0, error_rate_pct: 0 },
                { tool: 'b', count: 60, pct: 60, errors: 0, error_rate_pct: 0 },
            ],
        })

        expect(computeConcentratedRoutes([tiny])).toEqual({ focused: 0, total: 0 })
        expect(computeSpreadRoutes([tiny])).toBe(0)
        expect(computeTopErrorRoute([tiny])).toBeNull()
    })

    it('classifies eligible clusters by top-tool share', () => {
        const concentrated = cluster({
            id: 1,
            tool_distribution: [{ tool: 'a', count: 90, pct: 90, errors: 0, error_rate_pct: 0 }],
        })
        const spread = cluster({
            id: 2,
            tool_distribution: [
                { tool: 'a', count: 40, pct: 40, errors: 0, error_rate_pct: 0 },
                { tool: 'b', count: 35, pct: 35, errors: 0, error_rate_pct: 0 },
                { tool: 'c', count: 25, pct: 25, errors: 0, error_rate_pct: 0 },
            ],
        })

        expect(computeConcentratedRoutes([concentrated, spread])).toEqual({ focused: 1, total: 2 })
        expect(computeSpreadRoutes([concentrated, spread])).toBe(1)
    })

    it('picks the top error route by error count among eligible clusters', () => {
        const highRateLowVolume = cluster({ id: 1, call_count: 10, error_count: 4, error_rate_pct: 40 })
        const lowRateHighVolume = cluster({ id: 2, call_count: 1000, error_count: 100, error_rate_pct: 10 })

        expect(computeTopErrorRoute([highRateLowVolume, lowRateHighVolume])?.id).toBe(2)
    })

    // The backend rounds error_rate_pct to one decimal, so a cluster with errors
    // below 0.05% arrives as 0.0 and must still count as an error route.
    it.each<[string, number, boolean]>([
        ['has no errors at all', 0, false],
        ['has errors that round down to 0.0%', 3, true],
    ])('surfaces a cluster that %s', (_case, errorCount, isSurfaced) => {
        const rounded = cluster({ call_count: 10000, error_count: errorCount, error_rate_pct: 0 })

        expect(computeTopErrorRoute([rounded]) !== null).toBe(isSurfaced)
    })
})
