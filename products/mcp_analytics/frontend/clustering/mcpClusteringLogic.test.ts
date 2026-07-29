import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsIntentClustersRetrieve } from '../generated/api'
import type { MCPIntentClusterApi, MCPIntentClusterSnapshotApi } from '../generated/api.schemas'
import { MAX_HEATMAP_TOOL_COLUMNS, MAX_VISIBLE_CLUSTERS, mcpClusteringLogic } from './mcpClusteringLogic'

jest.mock('lib/api')
jest.mock('../generated/api', () => ({
    mcpAnalyticsIntentClustersRetrieve: jest.fn(),
    mcpAnalyticsIntentClustersRecompute: jest.fn(),
}))

const mockRetrieve = mcpAnalyticsIntentClustersRetrieve as jest.Mock

function cluster(id: number, overrides: Partial<MCPIntentClusterApi> = {}): MCPIntentClusterApi {
    return {
        id,
        label: `intent ${id}`,
        intent_count: 1,
        session_count: 1,
        call_count: 100 - id,
        error_count: 0,
        error_rate_pct: 0,
        routing_entropy: 0,
        // Two tools per cluster: a high-volume one unique to the cluster and a
        // 1-call long-tail one, so the snapshot carries 2× clusters distinct tools.
        tool_distribution: [
            { tool: `tool-${id}`, count: 100 - id, pct: 99, errors: 0, error_rate_pct: 0 },
            { tool: `tail-${id}`, count: 1, pct: 1, errors: 0, error_rate_pct: 0 },
        ],
        sample_intents: [`intent ${id}`],
        journey: null,
        ...overrides,
    }
}

// 5 more clusters than the visible cap, sorted-by-calls order = ascending id.
const N_CLUSTERS = MAX_VISIBLE_CLUSTERS + 5
const HIGH_ERROR_ID = N_CLUSTERS - 1

const SNAPSHOT: MCPIntentClusterSnapshotApi = {
    status: 'idle',
    error_message: '',
    last_computed_at: '2026-07-27T22:12:10Z',
    last_computed_by_email: 'test@posthog.com',
    clusters: Array.from({ length: N_CLUSTERS }, (_, i) =>
        // The last cluster has the fewest calls but the worst error rate, so it
        // only enters the visible set under the errors sort.
        cluster(i, i === HIGH_ERROR_ID ? { error_rate_pct: 50, error_count: 10 } : {})
    ),
    computed_with: {
        distance_threshold: 0.2,
        embedding_model: 'test',
        n_intents: N_CLUSTERS,
        n_clusters: N_CLUSTERS,
    },
}

describe('mcpClusteringLogic', () => {
    let logic: ReturnType<typeof mcpClusteringLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        mockRetrieve.mockResolvedValue(SNAPSHOT)
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('caps the visible clusters and expands them all on showAllClusters', () => {
        expect(logic.values.sortedClusters).toHaveLength(N_CLUSTERS)
        expect(logic.values.visibleClusters).toHaveLength(MAX_VISIBLE_CLUSTERS)
        expect(logic.values.hiddenClusterCount).toBe(N_CLUSTERS - MAX_VISIBLE_CLUSTERS)

        logic.actions.showAllClusters()

        expect(logic.values.visibleClusters).toHaveLength(N_CLUSTERS)
        expect(logic.values.hiddenClusterCount).toBe(0)
    })

    it('slices the visible set after sorting, so re-sorting surfaces clusters outside the call-count top', () => {
        // Lowest call count, so it's hidden under the default calls sort…
        expect(logic.values.visibleClusters.some((c) => c.id === HIGH_ERROR_ID)).toBe(false)

        logic.actions.setSortKey('errors')

        // …but worst error rate, so it leads once sorted by errors.
        expect(logic.values.visibleClusters[0].id).toBe(HIGH_ERROR_ID)
        expect(logic.values.visibleClusters).toHaveLength(MAX_VISIBLE_CLUSTERS)
    })

    it('caps heatmap tool columns by call volume and reports the full tool count', () => {
        expect(logic.values.toolColumns).toHaveLength(MAX_HEATMAP_TOOL_COLUMNS)
        // Highest-volume tool leads; the 1-call long-tail tools are what get cut.
        expect(logic.values.toolColumns[0]).toBe('tool-0')
        expect(logic.values.totalToolCount).toBe(N_CLUSTERS * 2)
    })

    it('reports the true cluster count from computed_with when the snapshot is truncated', async () => {
        expect(logic.values.totalClusterCount).toBe(N_CLUSTERS)

        // The backend stores only the top clusters; n_clusters keeps the run's full count.
        // Status row, scorecards, and the dashboard KPI must report that, not clusters.length.
        mockRetrieve.mockResolvedValue({
            ...SNAPSHOT,
            computed_with: { ...SNAPSHOT.computed_with!, n_clusters: 500 },
        })
        logic.actions.loadSnapshot()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.totalClusterCount).toBe(500)
    })
})
