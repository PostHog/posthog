import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { urls } from '~/scenes/urls'
import { initKeaTests } from '~/test/init'

import { mcpAnalyticsIntentClustersRetrieve } from '../generated/api'
import type {
    MCPIntentClusterApi,
    MCPIntentClusterSnapshotApi,
    MCPIntentClusterToolEntryApi,
    MCPToolPivotApi,
    MCPToolPivotClusterEntryApi,
} from '../generated/api.schemas'
import {
    type ClusterFilter,
    type RouteShape,
    clusterCategories,
    fitDomain,
    mcpClusteringLogic,
    routeShape,
    routingSegments,
    toolClusterRows,
    weightedMeanFit,
} from './mcpClusteringLogic'

jest.mock('lib/api')
jest.mock('../generated/api', () => ({
    mcpAnalyticsIntentClustersRetrieve: jest.fn(),
    mcpAnalyticsIntentClustersRecompute: jest.fn(),
}))

const mockRetrieve = mcpAnalyticsIntentClustersRetrieve as jest.Mock
const mockQuery = api.query as jest.Mock

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

/** Tool entries from `[tool, pct]` pairs; counts track pct so call-weighted maths stay checkable. */
function dist(pairs: [string, number][], errorRatePct = 0): MCPIntentClusterToolEntryApi[] {
    return pairs.map(([tool, pct]) => ({
        tool,
        count: pct,
        pct,
        errors: Math.round((pct * errorRatePct) / 100),
        error_rate_pct: errorRatePct,
    }))
}

// One cluster per route shape, so a scorecard count and its filter can be compared
// against a set whose shapes are known by construction.
const CONCENTRATED_ID = 1
const SPREAD_ID = 3
const MIXED_ID = 4
const NO_TOOLS_ID = 5
const FAILING_ID = 6

const SHAPED_CLUSTERS: MCPIntentClusterApi[] = [
    cluster(CONCENTRATED_ID, {
        tool_distribution: dist([
            ['a', 90],
            ['b', 10],
        ]),
    }),
    cluster(2, {
        tool_distribution: dist([
            ['a', 95],
            ['c', 5],
        ]),
    }),
    cluster(SPREAD_ID, {
        tool_distribution: dist([
            ['a', 40],
            ['b', 35],
            ['c', 25],
        ]),
    }),
    cluster(MIXED_ID, {
        tool_distribution: dist([
            ['a', 60],
            ['b', 40],
        ]),
    }),
    cluster(NO_TOOLS_ID, { tool_distribution: [] }),
    cluster(FAILING_ID, { tool_distribution: dist([['a', 100]], 30), error_count: 30, error_rate_pct: 30 }),
]

const SNAPSHOT: MCPIntentClusterSnapshotApi = {
    status: 'idle',
    error_message: '',
    last_computed_at: '2026-07-27T22:12:10Z',
    last_computed_by_email: 'test@posthog.com',
    clusters: SHAPED_CLUSTERS,
    // The tool pivot has its own fixtures further down, so the cluster
    // selectors under test here see an empty one.
    tools: [],
    tool_overlaps: [],
    computed_with: {
        distance_threshold: 0.2,
        embedding_model: 'test',
        n_intents: SHAPED_CLUSTERS.length,
        n_clusters: SHAPED_CLUSTERS.length,
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

    // The scorecards are the entry point into the list: each one states a count and
    // filters to that set. If the counter and the filter predicate drift apart, a card
    // reading "1 spread route" filters to a different number of rows.
    it.each([
        ['concentrated' as ClusterFilter, 'concentrated' as RouteShape],
        ['spread' as ClusterFilter, 'spread' as RouteShape],
        ['mixed' as ClusterFilter, 'mixed' as RouteShape],
    ])('the %s scorecard count is exactly what its filter shows', (filter, shape) => {
        const counted = logic.values.routeShapeCounts[shape]

        logic.actions.setClusterFilter(filter)

        expect(logic.values.filteredClusters).toHaveLength(counted)
        expect(logic.values.filteredClusters.every((c) => routeShape(c) === shape)).toBe(true)
    })

    it('the failing scorecard count is exactly what its filter shows', () => {
        const counted = logic.values.routeShapeCounts.failing

        logic.actions.setClusterFilter('failing')

        expect(counted).toBe(1)
        expect(logic.values.filteredClusters.map((c) => c.id)).toEqual([FAILING_ID])
    })

    // The counts also have to track the tool search, or a card reports a snapshot-wide
    // number while its filter — which applies the search too — returns fewer rows.
    it.each([
        ['concentrated' as ClusterFilter, 'concentrated' as RouteShape],
        ['spread' as ClusterFilter, 'spread' as RouteShape],
        ['mixed' as ClusterFilter, 'mixed' as RouteShape],
    ])('the %s scorecard count tracks the tool search its filter also applies', (filter, shape) => {
        logic.actions.setToolSearch('b')

        // Only clusters 1, 3 and 4 carry a `b` tool, so the searched set holds one of each shape.
        expect(logic.values.routeShapeCounts.total).toBe(3)

        const counted = logic.values.routeShapeCounts[shape]
        logic.actions.setClusterFilter(filter)

        expect(logic.values.filteredClusters).toHaveLength(counted)
        expect(logic.values.filteredClusters.every((c) => routeShape(c) === shape)).toBe(true)
    })

    // Filtering used to leave the detail pane showing a cluster that is no longer in the
    // list, so the pane contradicted the selection it was supposed to reflect.
    it('moves the selection into the filtered set when the filter excludes it', () => {
        logic.actions.selectCluster(CONCENTRATED_ID)

        logic.actions.setClusterFilter('spread')

        expect(logic.values.selectedClusterId).toBe(SPREAD_ID)
        expect(logic.values.filteredClusters.map((c) => c.id)).toContain(logic.values.selectedClusterId)
    })

    it('keeps the selection when the filter still contains it', () => {
        logic.actions.selectCluster(SPREAD_ID)

        logic.actions.setClusterFilter('spread')

        expect(logic.values.selectedClusterId).toBe(SPREAD_ID)
    })

    // Without the url round-trip, sharing a link to a cluster silently lands the
    // recipient on whichever cluster happens to have the most calls.
    it('round-trips the selected cluster through the url', async () => {
        logic.actions.selectCluster(MIXED_ID)
        // kea-router coerces numeric search params on read, so compare the value not the type.
        expect(Number(router.values.searchParams.cluster)).toBe(MIXED_ID)

        logic.unmount()
        router.actions.push(urls.mcpAnalyticsIntentClustering(), { cluster: String(SPREAD_ID) })
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedClusterId).toBe(SPREAD_ID)
    })

    // A shared link opened after a recompute (or a hand-edited param) names a cluster the
    // snapshot no longer carries. Without reconciliation the fallback stays suppressed and
    // the detail pane lands empty; it should reselect the highest-traffic cluster instead.
    it('falls back to the top cluster when the url names one the snapshot lacks', async () => {
        logic.unmount()
        router.actions.push(urls.mcpAnalyticsIntentClustering(), { cluster: '999' })
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const top = [...SHAPED_CLUSTERS].sort((a, b) => b.call_count - a.call_count)[0]
        expect(logic.values.selectedClusterId).toBe(top.id)
        expect(logic.values.selectedCluster).not.toBeNull()
    })

    // Polling and recompute swap the whole snapshot, and the backend reassigns cluster ids
    // per run, so a valid selection can vanish. The pane must not keep pointing at a gone id.
    it('reselects a top cluster when a reloaded snapshot drops the selected id', async () => {
        logic.actions.selectCluster(FAILING_ID)
        expect(logic.values.selectedClusterId).toBe(FAILING_ID)

        const survivors = SHAPED_CLUSTERS.filter((c) => c.id !== FAILING_ID)
        mockRetrieve.mockResolvedValue({ ...SNAPSHOT, clusters: survivors })
        logic.actions.loadSnapshot()
        await expectLogic(logic).toFinishAllListeners()

        expect(survivors.map((c) => c.id)).toContain(logic.values.selectedClusterId)
        expect(logic.values.selectedCluster).not.toBeNull()
    })

    it('reports the true cluster count from computed_with when the snapshot is truncated', async () => {
        expect(logic.values.totalClusterCount).toBe(SHAPED_CLUSTERS.length)

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

// Categories live on the events, not in the precomputed snapshot, so they arrive as a
// separate tool→category map that every view joins against by tool name.
describe('mcpClusteringLogic category scope', () => {
    let logic: ReturnType<typeof mcpClusteringLogic.build>

    // `a` and `c` are Data, `b` is Insights, and `loner` deliberately has no category row.
    const CATEGORY_MAP = [
        { tool: 'a', category: 'Data' },
        { tool: 'b', category: 'Insights' },
        { tool: 'c', category: 'Data' },
    ]

    // Distinct call counts so the pivot's volume ordering is explicit rather than
    // resting on sort stability.
    const named = (tool: string, callCount: number): MCPToolPivotApi => ({
        ...pivot([]),
        tool,
        call_count: callCount,
    })

    const SCOPED_SNAPSHOT: MCPIntentClusterSnapshotApi = {
        ...SNAPSHOT,
        tools: [named('a', 30), named('b', 20), named('loner', 10)],
        tool_overlaps: [
            {
                tool_a: 'a',
                tool_b: 'b',
                contested_calls: 10,
                sessions_with_both: 2,
                sessions_with_either: 5,
                top_cluster_id: SPREAD_ID,
            },
            {
                tool_a: 'loner',
                tool_b: 'stranger',
                contested_calls: 3,
                sessions_with_both: 1,
                sessions_with_either: 4,
                top_cluster_id: SPREAD_ID,
            },
        ],
    }

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        mockRetrieve.mockResolvedValue(SCOPED_SNAPSHOT)
        mockQuery.mockResolvedValue({ results: CATEGORY_MAP })
        router.actions.push(urls.mcpAnalyticsIntentClustering())
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    // Selecting nothing has to mean everything. An empty selection that produced an empty
    // scope set instead of "no scope" would blank the whole tab on first load.
    it('shows every cluster and tool while no category is selected', () => {
        expect(logic.values.selectedCategories).toEqual([])
        expect(logic.values.scopedClusters).toHaveLength(SHAPED_CLUSTERS.length)
        expect(logic.values.scopedTools.map((t) => t.tool)).toEqual(['a', 'b', 'loner'])
    })

    // Matching only the cluster's top tool would be an easy simplification, and it would
    // silently drop clusters whose secondary tool is the one in the chosen category.
    it('keeps a cluster when any tool it routes to is in the category, not just its top one', () => {
        logic.actions.setSelectedCategories(['Insights'])

        // `b` is second by volume in clusters 1 and 4, and third in cluster 3.
        expect(logic.values.scopedClusters.map((c) => c.id)).toEqual([CONCENTRATED_ID, SPREAD_ID, MIXED_ID])
    })

    it('drops clusters routing to no tool in the selected categories', () => {
        logic.actions.setSelectedCategories(['Insights'])

        const ids = logic.values.scopedClusters.map((c) => c.id)
        expect(ids).not.toContain(NO_TOOLS_ID)
        expect(ids).not.toContain(FAILING_ID)
    })

    // A tool the map never mentions belongs to no category, so a live filter must exclude
    // it — keeping it visible would contradict the scope the user picked.
    it('excludes an uncategorized tool once a category is selected', () => {
        expect(logic.values.scopedTools.map((t) => t.tool)).toContain('loner')

        logic.actions.setSelectedCategories(['Data'])

        expect(logic.values.scopedTools.map((t) => t.tool)).toEqual(['a'])
    })

    // Either side in scope, not both: a contested pair is worth seeing precisely when the
    // competitor sits in another category.
    it('keeps a contested pair when only one side is in scope', () => {
        logic.actions.setSelectedCategories(['Insights'])

        expect(logic.values.toolOverlaps.map((o) => [o.tool_a, o.tool_b])).toEqual([['a', 'b']])
    })

    it('moves the selection into the scoped set when the category excludes it', () => {
        logic.actions.selectTool('loner')

        logic.actions.setSelectedCategories(['Data'])

        expect(logic.values.selectedToolName).toBe('a')
    })

    // A shared `?categories=…&cluster=…` link applies the selection before the category map
    // has loaded, so the scope isn't known yet and the reconcile has nothing to work with.
    // Once the map arrives the selection must move into the scoped list — otherwise the list
    // is scoped but the detail pane sits on a cluster the scope excludes, with no row lit up.
    it('reconciles an out-of-scope url selection once the category map arrives', async () => {
        logic.unmount()
        router.actions.push(urls.mcpAnalyticsIntentClustering(), {
            categories: 'Data',
            cluster: String(NO_TOOLS_ID),
        })
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // NO_TOOLS_ID routes to no Data tool, so it is never in the Data scope.
        const scopedIds = logic.values.scopedClusters.map((c) => c.id)
        expect(scopedIds).not.toContain(NO_TOOLS_ID)
        expect(scopedIds).toContain(logic.values.selectedClusterId)
    })

    // The 30-day category window is wider than the snapshot's, so a category can name only
    // tools the snapshot never carried. Its scope then matches nothing, and the selection
    // must clear rather than strand the detail pane on a cluster the scope excludes.
    it('clears the selection when the selected category matches nothing in the snapshot', async () => {
        logic.unmount()
        mockQuery.mockResolvedValue({ results: [...CATEGORY_MAP, { tool: 'ghost', category: 'Ghost' }] })
        router.actions.push(urls.mcpAnalyticsIntentClustering())
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSelectedCategories(['Ghost'])

        expect(logic.values.scopedClusters).toEqual([])
        expect(logic.values.scopedTools).toEqual([])
        expect(logic.values.selectedClusterId).toBeNull()
        expect(logic.values.selectedToolName).toBeNull()
    })

    // A recompute reloads the snapshot but not the category map, so the reload's own reconcile
    // has to honour the active scope. Reconciling against the unscoped snapshot would fall back
    // to the highest-volume cluster overall, which can sit outside the scope — stranding the
    // detail there while the list shows the scoped subset.
    it('falls back to the scoped top, not the snapshot top, when a recompute drops the selection', async () => {
        logic.actions.setSelectedCategories(['Insights'])
        logic.actions.selectCluster(CONCENTRATED_ID)
        expect(logic.values.selectedClusterId).toBe(CONCENTRATED_ID)

        // Drop the selected cluster. The new unscoped top is cluster 2, which routes only to Data
        // tools, so an unscoped fallback would land the detail outside the Insights scope.
        const survivors = SHAPED_CLUSTERS.filter((c) => c.id !== CONCENTRATED_ID)
        mockRetrieve.mockResolvedValue({ ...SCOPED_SNAPSHOT, clusters: survivors })
        logic.actions.loadSnapshot()
        await expectLogic(logic).toFinishAllListeners()

        // SPREAD_ID is the highest-volume Insights cluster left, so the reconcile picks it.
        expect(logic.values.selectedClusterId).toBe(SPREAD_ID)
        expect(logic.values.scopedClusters.map((c) => c.id)).toContain(logic.values.selectedClusterId)
    })

    // The map is a slower query than the stored snapshot and can also fail or return nothing.
    // A category carried in from a bookmarked url must not scope every view down to nothing when
    // there is no map to scope against — the views render unscoped until (if ever) the map lands.
    it('applies no scope when a category is selected but the map load fails', async () => {
        logic.unmount()
        mockQuery.mockRejectedValue(new Error('clickhouse timeout'))
        router.actions.push(urls.mcpAnalyticsIntentClustering(), { categories: 'Data' })
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedCategories).toEqual(['Data'])
        expect(logic.values.categoryMap).toEqual([])
        expect(logic.values.toolsInScope).toBeNull()
        expect(logic.values.scopedClusters).toHaveLength(SHAPED_CLUSTERS.length)
        expect(logic.values.scopedTools.map((t) => t.tool)).toEqual(['a', 'b', 'loner'])
    })

    // Requesting the map sets a flag that stops urlToAction refetching on every click. Left set
    // through a failure, one blip makes the tab unfilterable for the session; cleared without a
    // bound, a failing ClickHouse query lands behind every row the user clicks.
    it('retries a failed category map once, then stops', async () => {
        logic.unmount()
        mockQuery.mockRejectedValue(new Error('clickhouse timeout'))
        router.actions.push(urls.mcpAnalyticsIntentClustering())
        const before = mockQuery.mock.calls.length
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(mockQuery.mock.calls.length - before).toBe(1)

        logic.actions.selectCluster(SPREAD_ID)
        await expectLogic(logic).toFinishAllListeners()
        expect(mockQuery.mock.calls.length - before).toBe(2)

        logic.actions.selectTool('b')
        router.actions.push(urls.mcpAnalyticsIntentClustering(), { view: 'tools' })
        await expectLogic(logic).toFinishAllListeners()
        expect(mockQuery.mock.calls.length - before).toBe(2)
    })

    // The selector hides itself when no tool carries a category, which is also what a failed
    // map load looks like. Offering only what the map knows would hide a category arriving from
    // a bookmarked url behind no control at all, leaving no way to see or clear it.
    it('keeps a url category clearable when the map load fails', async () => {
        logic.unmount()
        mockQuery.mockRejectedValue(new Error('clickhouse timeout'))
        router.actions.push(urls.mcpAnalyticsIntentClustering(), { categories: 'Data' })
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.availableCategories).toEqual([])
        expect(logic.values.categoryScopeOptions).toEqual(['Data'])
    })

    // Tool names come from events, so a call named `__proto__` or `constructor` can reach the
    // category map. A plain-object lookup resolves those to inherited values and throws on the
    // `.includes` check, taking the whole view down; the map has to be prototype-free.
    it('handles tool names that collide with object prototype keys', async () => {
        logic.unmount()
        mockQuery.mockResolvedValue({
            results: [
                { tool: '__proto__', category: 'Data' },
                { tool: '__proto__', category: 'Insights' },
                { tool: 'constructor', category: 'Data' },
            ],
        })
        router.actions.push(urls.mcpAnalyticsIntentClustering())
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.categoriesByTool['__proto__']).toEqual(['Data', 'Insights'])
        expect(logic.values.categoriesByTool['constructor']).toEqual(['Data'])
    })

    // A single category comes back from the url as a bare string rather than an array,
    // which would otherwise scope to the individual characters of its name.
    it.each([
        ['one category', 'Insights', ['Insights']],
        ['several categories', ['Data', 'Insights'], ['Data', 'Insights']],
    ])('round-trips %s through the url', async (_label, param, expected) => {
        logic.unmount()
        router.actions.push(urls.mcpAnalyticsIntentClustering(), { categories: param })
        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.selectedCategories).toEqual(expected)
    })

    it('offers only categories that some tool actually belongs to', () => {
        expect(logic.values.availableCategories).toEqual(['Data', 'Insights'])
    })

    // Selecting a cluster rewrites the url, which re-runs urlToAction. Refetching the map
    // on every click would put a ClickHouse query behind each row.
    it('fetches the category map once however often the url is rewritten', () => {
        const before = mockQuery.mock.calls.length

        logic.actions.selectCluster(SPREAD_ID)
        logic.actions.selectTool('b')
        router.actions.push(urls.mcpAnalyticsIntentClustering(), { view: 'tools' })

        expect(mockQuery.mock.calls.length).toBe(before)
    })

    // The dashboard tab connects to this logic purely for cluster counts, so mounting it
    // there must not fire the category query.
    it('does not fetch the category map when mounted away from the clustering tab', async () => {
        logic.unmount()
        jest.clearAllMocks()
        mockRetrieve.mockResolvedValue(SCOPED_SNAPSHOT)
        router.actions.push(urls.mcpAnalyticsDashboard())

        logic = mcpClusteringLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockQuery).not.toHaveBeenCalled()
        expect(logic.values.availableCategories).toEqual([])
    })
})

describe('mcpClusteringLogic helpers', () => {
    // A cluster with no tool distribution used to fall through to a `?? 100` default and
    // be counted as the best-routed shape there is, inflating the headline number.
    it.each([
        [
            'one tool takes at least 80%',
            dist([
                ['a', 90],
                ['b', 10],
            ]),
            'concentrated',
        ],
        ['a single tool takes everything', dist([['a', 100]]), 'concentrated'],
        [
            'no tool reaches half across several',
            dist([
                ['a', 40],
                ['b', 35],
                ['c', 25],
            ]),
            'spread',
        ],
        [
            'the top tool sits between the bands',
            dist([
                ['a', 60],
                ['b', 40],
            ]),
            'mixed',
        ],
        ['there is no distribution at all', [], 'mixed'],
    ])('routeShape is %s -> %s', (_name, tool_distribution, expected) => {
        expect(routeShape(cluster(1, { tool_distribution }))).toBe(expected)
    })

    // The list row draws one bar per segment. A remainder emitted for a cluster that has
    // nothing left over draws a phantom segment, and 65% of real clusters call one tool.
    it.each([
        ['a single tool', dist([['a', 100]]), [{ tool: 'a', pct: 100, toolCount: 1 }]],
        [
            'exactly the segment cap',
            dist([
                ['a', 50],
                ['b', 30],
                ['c', 20],
            ]),
            [
                { tool: 'a', pct: 50, toolCount: 1 },
                { tool: 'b', pct: 30, toolCount: 1 },
                { tool: 'c', pct: 20, toolCount: 1 },
            ],
        ],
        [
            'more tools than the cap, remainder aggregated',
            dist([
                ['a', 40],
                ['b', 30],
                ['c', 20],
                ['d', 6],
                ['e', 4],
            ]),
            [
                { tool: 'a', pct: 40, toolCount: 1 },
                { tool: 'b', pct: 30, toolCount: 1 },
                { tool: 'c', pct: 20, toolCount: 1 },
                { tool: null, pct: 10, toolCount: 2 },
            ],
        ],
        ['no tools', [], []],
    ])('routingSegments over %s', (_name, tool_distribution, expected) => {
        const segments = routingSegments(cluster(1, { tool_distribution }), 3)

        expect(segments.map(({ tool, pct, toolCount }) => ({ tool, pct, toolCount }))).toEqual(expected)
    })

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
    // Two tools in one category used to mean the badge rendered twice, which React also
    // flags as a duplicate key.
    it('clusterCategories lists each category once, busiest tool first', () => {
        const c = cluster(1, {
            tool_distribution: dist([
                ['b', 60],
                ['a', 30],
                ['c', 10],
            ]),
        })

        expect(clusterCategories(c, { a: ['Data'], b: ['Insights'], c: ['Data'] })).toEqual(['Insights', 'Data'])
    })

    it('clusterCategories is empty when none of the cluster tools are mapped', () => {
        expect(clusterCategories(cluster(1, { tool_distribution: dist([['a', 100]]) }), {})).toEqual([])
    })

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
