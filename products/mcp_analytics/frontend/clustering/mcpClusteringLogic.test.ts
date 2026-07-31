import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { mcpAnalyticsIntentClustersRetrieve } from '../generated/api'
import type {
    MCPIntentClusterApi,
    MCPIntentClusterSnapshotApi,
    MCPToolPivotApi,
    MCPToolPivotClusterEntryApi,
} from '../generated/api.schemas'
import {
    MAX_HEATMAP_TOOL_COLUMNS,
    MAX_VISIBLE_CLUSTERS,
    fitDomain,
    mcpClusteringLogic,
    toolClusterRows,
    weightedMeanFit,
} from './mcpClusteringLogic'

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
        switches: [],
        self_retries: [],
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
    // The tool pivot has its own fixtures further down, so the cluster/heatmap
    // selectors under test here see an empty one.
    tools: [],
    tool_overlaps: [],
    computed_with: {
        distance_threshold: 0.2,
        embedding_model: 'test',
        n_intents: N_CLUSTERS,
        n_clusters: N_CLUSTERS,
        // Coverage metadata feeds ClusteringCoverageBanner, not these selectors.
        corpus: null,
        sampled_sessions: null,
        window_sessions: null,
        session_coverage_pct: null,
        intent_coverage_pct: null,
        imputed_call_pct: null,
        unattributed_call_pct: null,
        corpus_call_coverage_pct: null,
        advertisement_coverage_pct: null,
        n_tools: null,
        dropped_tools: null,
        dropped_overlap_pairs: null,
        description_coverage_pct: null,
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

function entry(overrides: Partial<MCPToolPivotClusterEntryApi>): MCPToolPivotClusterEntryApi {
    return {
        cluster_id: 0,
        calls: 1,
        capture_pct: 100,
        rank: 1,
        description_fit: null,
        top_competitor: null,
        ...overrides,
    }
}

function pivot(clusters: MCPToolPivotClusterEntryApi[]): MCPToolPivotApi {
    return {
        tool: 't',
        call_count: clusters.reduce((sum, c) => sum + c.calls, 0),
        error_count: 0,
        session_count: 1,
        contested_score: null,
        advertised_sessions: 0,
        called_when_advertised: 0,
        discovery_rate_pct: null,
        description: null,
        n_clusters_served: clusters.length,
        clusters,
    }
}

describe('mcpClusteringLogic helpers', () => {
    // The scatter plots one fit value per tool; if the weighting silently broke,
    // a tool's dominant intent would no longer dominate its plotted position.
    it('weightedMeanFit weights each cluster fit by its call volume', () => {
        const tool = pivot([
            entry({ cluster_id: 0, calls: 9, description_fit: 1.0 }),
            entry({ cluster_id: 1, calls: 1, description_fit: 0.0 }),
        ])
        expect(weightedMeanFit(tool)).toBeCloseTo(0.9)
    })

    it.each([
        ['no cluster has a fit', [entry({ description_fit: null })]],
        ['no clusters at all', [] as MCPToolPivotClusterEntryApi[]],
        ['fits exist but carry zero calls', [entry({ calls: 0, description_fit: 0.5 })]],
    ])('weightedMeanFit is null when %s', (_name, clusters) => {
        expect(weightedMeanFit(pivot(clusters))).toBeNull()
    })

    it('weightedMeanFit ignores fitless clusters instead of treating them as zero', () => {
        const tool = pivot([
            entry({ cluster_id: 0, calls: 1, description_fit: 0.8 }),
            entry({ cluster_id: 1, calls: 99, description_fit: null }),
        ])
        expect(weightedMeanFit(tool)).toBeCloseTo(0.8)
    })

    // The pivot no longer ships the cluster's label with every entry, so a broken
    // join renders the intents table with blank rows instead of intent text.
    it('toolClusterRows joins each entry to the cluster it points at', () => {
        const rows = toolClusterRows(pivot([entry({ cluster_id: 3 }), entry({ cluster_id: 1 })]), [
            cluster(1),
            cluster(3),
        ])

        expect(rows.map((row) => row.cluster.label)).toEqual(['intent 3', 'intent 1'])
    })

    it('toolClusterRows drops entries with no matching cluster rather than rendering them blank', () => {
        expect(toolClusterRows(pivot([entry({ cluster_id: 99 })]), [cluster(1)])).toEqual([])
    })

    // Fits for one server's tools sit in a narrow band; anchoring the axis at 0
    // piles every bubble against the right edge and puts the median line through
    // the pile, which is exactly the quadrant read the chart promises.
    it('fitDomain brackets the observed band instead of anchoring at zero', () => {
        const [low, high] = fitDomain([0.55, 0.7, 0.85])

        expect(low).toBeGreaterThan(0.4)
        expect(low).toBeLessThan(0.55)
        expect(high).toBeGreaterThan(0.85)
        expect(high).toBeLessThanOrEqual(1)
    })

    it.each([
        ['every tool has the same fit', [0.7, 0.7]],
        ['there is a single tool', [0.7]],
    ])('fitDomain keeps a usable span when %s', (_name, fits) => {
        const [low, high] = fitDomain(fits)

        expect(high - low).toBeGreaterThan(0)
    })
})
