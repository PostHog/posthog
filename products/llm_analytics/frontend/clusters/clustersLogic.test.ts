import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { clustersLogic } from './clustersLogic'
import { NOISE_CLUSTER_ID } from './constants'
import { EvaluationItemAttributes } from './traceSummaryLoader'
import { Cluster, ClusterMetrics, ClusteringRun } from './types'

describe('clustersLogic', () => {
    let logic: ReturnType<typeof clustersLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = clustersLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('reducers', () => {
        describe('selectedRunId', () => {
            it('sets selected run ID', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setSelectedRunId('test-run-123')
                }).toMatchValues({
                    selectedRunId: 'test-run-123',
                })
            })

            it('clears selected run ID with null', async () => {
                logic.actions.setSelectedRunId('test-run-123')

                await expectLogic(logic, () => {
                    logic.actions.setSelectedRunId(null)
                }).toMatchValues({
                    selectedRunId: null,
                })
            })
        })

        describe('expandedClusterIds', () => {
            it('toggles cluster expansion', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleClusterExpanded(0)
                }).toMatchValues({
                    expandedClusterIds: new Set([0]),
                })

                await expectLogic(logic, () => {
                    logic.actions.toggleClusterExpanded(0)
                }).toMatchValues({
                    expandedClusterIds: new Set(),
                })
            })

            it('handles multiple expanded clusters', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleClusterExpanded(0)
                    logic.actions.toggleClusterExpanded(1)
                    logic.actions.toggleClusterExpanded(2)
                }).toMatchValues({
                    expandedClusterIds: new Set([0, 1, 2]),
                })

                await expectLogic(logic, () => {
                    logic.actions.toggleClusterExpanded(1)
                }).toMatchValues({
                    expandedClusterIds: new Set([0, 2]),
                })
            })
        })

        describe('traceSummaries', () => {
            it('sets trace summaries', async () => {
                const summaries = {
                    'trace-1': {
                        traceId: 'trace-1',
                        title: 'Test Trace',
                        flowDiagram: 'diagram',
                        bullets: 'bullets',
                        interestingNotes: 'notes',
                        timestamp: '2025-01-05T10:00:00Z',
                    },
                }

                await expectLogic(logic, () => {
                    logic.actions.setTraceSummaries(summaries)
                }).toMatchValues({
                    traceSummaries: summaries,
                })
            })

            it('merges new summaries with existing', async () => {
                const summary1 = {
                    'trace-1': {
                        traceId: 'trace-1',
                        title: 'Trace 1',
                        flowDiagram: '',
                        bullets: '',
                        interestingNotes: '',
                        timestamp: '',
                    },
                }
                const summary2 = {
                    'trace-2': {
                        traceId: 'trace-2',
                        title: 'Trace 2',
                        flowDiagram: '',
                        bullets: '',
                        interestingNotes: '',
                        timestamp: '',
                    },
                }

                logic.actions.setTraceSummaries(summary1)

                await expectLogic(logic, () => {
                    logic.actions.setTraceSummaries(summary2)
                }).toMatchValues({
                    traceSummaries: { ...summary1, ...summary2 },
                })
            })
        })

        describe('isScatterPlotExpanded', () => {
            it('defaults to expanded', () => {
                expect(logic.values.isScatterPlotExpanded).toBe(true)
            })

            it('toggles scatter plot expansion', async () => {
                await expectLogic(logic, () => {
                    logic.actions.toggleScatterPlotExpanded()
                }).toMatchValues({
                    isScatterPlotExpanded: false,
                })

                await expectLogic(logic, () => {
                    logic.actions.toggleScatterPlotExpanded()
                }).toMatchValues({
                    isScatterPlotExpanded: true,
                })
            })
        })

        describe('clusterMetrics', () => {
            it('defaults to empty object', () => {
                expect(logic.values.clusterMetrics).toEqual({})
            })

            it('sets cluster metrics', async () => {
                const metrics: Record<number, ClusterMetrics> = {
                    0: {
                        avgCost: 0.05,
                        avgLatency: 1.5,
                        avgTokens: 500,
                        totalCost: 0.5,
                        errorRate: 0.1,
                        errorCount: 1,
                        itemCount: 10,
                    },
                    1: {
                        avgCost: 0.02,
                        avgLatency: 0.8,
                        avgTokens: 200,
                        totalCost: 0.2,
                        errorRate: 0,
                        errorCount: 0,
                        itemCount: 10,
                    },
                }

                await expectLogic(logic, () => {
                    logic.actions.setClusterMetrics(metrics)
                }).toMatchValues({
                    clusterMetrics: metrics,
                })
            })

            it('clears metrics when clustering level changes', async () => {
                const metrics: Record<number, ClusterMetrics> = {
                    0: {
                        avgCost: 0.05,
                        avgLatency: 1.5,
                        avgTokens: 500,
                        totalCost: 0.5,
                        errorRate: 0.1,
                        errorCount: 1,
                        itemCount: 10,
                    },
                }

                logic.actions.setClusterMetrics(metrics)
                expect(logic.values.clusterMetrics).toEqual(metrics)

                await expectLogic(logic, () => {
                    logic.actions.setClusteringLevel('generation')
                }).toMatchValues({
                    clusterMetrics: {},
                })
            })
        })

        describe('clusterMetricsLoading', () => {
            it('defaults to false', () => {
                expect(logic.values.clusterMetricsLoading).toBe(false)
            })

            it('sets loading state', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setClusterMetricsLoading(true)
                }).toMatchValues({
                    clusterMetricsLoading: true,
                })

                await expectLogic(logic, () => {
                    logic.actions.setClusterMetricsLoading(false)
                }).toMatchValues({
                    clusterMetricsLoading: false,
                })
            })
        })
    })

    describe('selectors', () => {
        describe('breadcrumbs', () => {
            it('returns clusters breadcrumb with icon type', () => {
                expect(logic.values.breadcrumbs).toEqual([
                    {
                        key: 'LLMAnalyticsClusters',
                        name: 'Clusters',
                        path: '/llm-analytics/clusters',
                        iconType: 'llm_clusters',
                    },
                ])
            })
        })

        const mockCluster1: Cluster = {
            cluster_id: 0,
            size: 10,
            title: 'Cluster A',
            description: 'Description A',
            traces: {
                'trace-1': {
                    distance_to_centroid: 0.1,
                    rank: 0,
                    x: 0.0,
                    y: 0.0,
                    timestamp: '2025-01-05T10:00:00Z',
                    trace_id: 'trace-1',
                },
                'trace-2': {
                    distance_to_centroid: 0.2,
                    rank: 1,
                    x: 0.1,
                    y: 0.1,
                    timestamp: '2025-01-05T11:00:00Z',
                    trace_id: 'trace-2',
                },
            },
            centroid: [1.0],
            centroid_x: 0.05,
            centroid_y: 0.05,
        }

        const mockCluster2: Cluster = {
            cluster_id: 1,
            size: 20,
            title: 'Cluster B',
            description: 'Description B',
            traces: {
                'trace-3': {
                    distance_to_centroid: 0.1,
                    rank: 0,
                    x: 1.0,
                    y: 1.0,
                    timestamp: '2025-01-05T12:00:00Z',
                    trace_id: 'trace-3',
                },
            },
            centroid: [2.0],
            centroid_x: 1.0,
            centroid_y: 1.0,
        }

        const mockNoiseCluster: Cluster = {
            cluster_id: NOISE_CLUSTER_ID,
            size: 5,
            title: 'Outliers',
            description: 'Noise points',
            traces: {
                'trace-noise-1': {
                    distance_to_centroid: 0.9,
                    rank: 0,
                    x: 5.0,
                    y: 5.0,
                    timestamp: '',
                    trace_id: 'trace-noise-1',
                },
            },
            centroid: [],
            centroid_x: 5.0,
            centroid_y: 5.0,
        }

        describe('sortedClusters', () => {
            it('returns empty array when no current run', () => {
                expect(logic.values.sortedClusters).toEqual([])
            })

            it('sorts clusters by size descending', async () => {
                const mockRun: ClusteringRun = {
                    runId: 'test-run',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-08T00:00:00Z',
                    totalItemsAnalyzed: 30,
                    clusters: [mockCluster1, mockCluster2],
                    timestamp: '2025-01-08T00:00:00Z',
                    clusteringParams: undefined,
                }

                // Set the current run via loader success action
                logic.actions.loadClusteringRunSuccess(mockRun)

                expect(logic.values.sortedClusters[0].cluster_id).toBe(1) // Size 20
                expect(logic.values.sortedClusters[1].cluster_id).toBe(0) // Size 10
            })
        })

        describe('isClusterExpanded', () => {
            it('returns false for non-expanded cluster', () => {
                expect(logic.values.isClusterExpanded(0)).toBe(false)
            })

            it('returns true for expanded cluster', () => {
                logic.actions.toggleClusterExpanded(0)
                expect(logic.values.isClusterExpanded(0)).toBe(true)
            })
        })

        describe('traceToClusterTitle', () => {
            it('maps trace IDs to cluster titles', async () => {
                const mockRun: ClusteringRun = {
                    runId: 'test-run',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-08T00:00:00Z',
                    totalItemsAnalyzed: 15,
                    clusters: [mockCluster1, mockCluster2],
                    timestamp: '2025-01-08T00:00:00Z',
                    clusteringParams: undefined,
                }

                logic.actions.loadClusteringRunSuccess(mockRun)

                const mapping = logic.values.traceToClusterTitle
                expect(mapping['trace-1']).toBe('Cluster A')
                expect(mapping['trace-2']).toBe('Cluster A')
                expect(mapping['trace-3']).toBe('Cluster B')
            })

            it('uses default title when cluster title is empty', async () => {
                const clusterWithoutTitle: Cluster = {
                    ...mockCluster1,
                    title: '',
                }

                const mockRun: ClusteringRun = {
                    runId: 'test-run',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-08T00:00:00Z',
                    totalItemsAnalyzed: 10,
                    clusters: [clusterWithoutTitle],
                    timestamp: '2025-01-08T00:00:00Z',
                    clusteringParams: undefined,
                }

                logic.actions.loadClusteringRunSuccess(mockRun)

                const mapping = logic.values.traceToClusterTitle
                expect(mapping['trace-1']).toBe('Cluster 0')
            })
        })

        describe('scatterPlotDatasets', () => {
            it('creates datasets for regular clusters', async () => {
                const mockRun: ClusteringRun = {
                    runId: 'test-run',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-08T00:00:00Z',
                    totalItemsAnalyzed: 15,
                    clusters: [mockCluster1, mockCluster2],
                    timestamp: '2025-01-08T00:00:00Z',
                    clusteringParams: undefined,
                }

                logic.actions.loadClusteringRunSuccess(mockRun)

                const datasets = logic.values.scatterPlotDatasets
                // 2 trace datasets + 2 centroid datasets
                expect(datasets.length).toBe(4)

                // Verify trace datasets have correct structure
                const traceDatasets = datasets.filter((d) => !d.label.includes('(centroid)'))
                expect(traceDatasets.length).toBe(2)
                expect(traceDatasets[0].pointStyle).toBe('circle')
            })

            it('uses crossRot style for outlier cluster', async () => {
                const mockRun: ClusteringRun = {
                    runId: 'test-run',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-08T00:00:00Z',
                    totalItemsAnalyzed: 15,
                    clusters: [mockCluster1, mockNoiseCluster],
                    timestamp: '2025-01-08T00:00:00Z',
                    clusteringParams: undefined,
                }

                logic.actions.loadClusteringRunSuccess(mockRun)

                const datasets = logic.values.scatterPlotDatasets
                const outlierDataset = datasets.find((d) => d.label === 'Outliers')

                expect(outlierDataset).toBeTruthy()
                expect(outlierDataset?.pointStyle).toBe('crossRot')
            })

            it('does not create centroid marker for outlier cluster', async () => {
                const mockRun: ClusteringRun = {
                    runId: 'test-run',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-08T00:00:00Z',
                    totalItemsAnalyzed: 15,
                    clusters: [mockCluster1, mockNoiseCluster],
                    timestamp: '2025-01-08T00:00:00Z',
                    clusteringParams: undefined,
                }

                logic.actions.loadClusteringRunSuccess(mockRun)

                const datasets = logic.values.scatterPlotDatasets
                const centroidDatasets = datasets.filter((d) => d.label.includes('(centroid)'))

                // Only one centroid for regular cluster, none for outliers
                expect(centroidDatasets.length).toBe(1)
                expect(centroidDatasets[0].label).toBe('Cluster A (centroid)')
            })

            it('includes trace metadata in data points', async () => {
                const mockRun: ClusteringRun = {
                    runId: 'test-run',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-08T00:00:00Z',
                    totalItemsAnalyzed: 10,
                    clusters: [mockCluster1],
                    timestamp: '2025-01-08T00:00:00Z',
                    clusteringParams: undefined,
                }

                logic.actions.loadClusteringRunSuccess(mockRun)

                const datasets = logic.values.scatterPlotDatasets
                const traceDataset = datasets.find((d) => d.label === 'Cluster A')

                expect(traceDataset?.data[0]).toMatchObject({
                    x: 0.0,
                    y: 0.0,
                    traceId: 'trace-1',
                    timestamp: '2025-01-05T10:00:00Z',
                })
            })
        })

        describe('effectiveRunId', () => {
            it('returns selected run ID when set', async () => {
                logic.actions.setSelectedRunId('selected-run')
                logic.actions.loadClusteringRunsSuccess([
                    { runId: 'first-run', windowEnd: '2025-01-08', label: 'First Run' },
                ])

                expect(logic.values.effectiveRunId).toBe('selected-run')
            })

            it('returns first run ID when none selected', async () => {
                logic.actions.loadClusteringRunsSuccess([
                    { runId: 'first-run', windowEnd: '2025-01-08', label: 'First Run' },
                    { runId: 'second-run', windowEnd: '2025-01-07', label: 'Second Run' },
                ])

                expect(logic.values.effectiveRunId).toBe('first-run')
            })

            it('returns null when no runs available', () => {
                expect(logic.values.effectiveRunId).toBe(null)
            })
        })

        describe('evaluation filter logic', () => {
            const sampleAttrs: Record<string, EvaluationItemAttributes> = {
                'id-pass-a': { evaluatorName: 'Accuracy', verdict: 'pass' },
                'id-pass-b': { evaluatorName: 'Accuracy', verdict: 'pass' },
                'id-fail-a': { evaluatorName: 'Accuracy', verdict: 'fail' },
                'id-fail-b': { evaluatorName: 'Relevance', verdict: 'fail' },
                'id-na-a': { evaluatorName: 'Relevance', verdict: 'n/a' },
            }

            const setEvalLevelAndAttrs = (): void => {
                logic.actions.setClusteringLevel('evaluation')
                logic.actions.setEvaluationItemAttributes(sampleAttrs)
            }

            describe('availableEvaluatorNames', () => {
                it('returns empty when no attributes are loaded', () => {
                    expect(logic.values.availableEvaluatorNames).toEqual([])
                })

                it('aggregates counts by evaluator name, descending', () => {
                    setEvalLevelAndAttrs()
                    expect(logic.values.availableEvaluatorNames).toEqual([
                        { name: 'Accuracy', count: 3 },
                        { name: 'Relevance', count: 2 },
                    ])
                })
            })

            describe('availableVerdictCounts', () => {
                it('returns zero for every verdict when no attributes are loaded', () => {
                    expect(logic.values.availableVerdictCounts).toEqual({
                        pass: 0,
                        fail: 0,
                        'n/a': 0,
                        unknown: 0,
                    })
                })

                it('counts verdicts across loaded attributes', () => {
                    setEvalLevelAndAttrs()
                    expect(logic.values.availableVerdictCounts).toEqual({
                        pass: 2,
                        fail: 2,
                        'n/a': 1,
                        unknown: 0,
                    })
                })
            })

            describe('evalFilterPredicate', () => {
                it('returns true for everything when clustering level is not evaluation', () => {
                    logic.actions.setClusteringLevel('trace')
                    logic.actions.setEvaluationItemAttributes(sampleAttrs)
                    logic.actions.setEvalEvaluatorNamesFilter(['Accuracy'])
                    logic.actions.setEvalVerdictsFilter(['pass'])

                    const predicate = logic.values.evalFilterPredicate
                    for (const id of Object.keys(sampleAttrs)) {
                        expect(predicate(id)).toBe(true)
                    }
                })

                it('returns true for everything when no filters are active', () => {
                    setEvalLevelAndAttrs()

                    const predicate = logic.values.evalFilterPredicate
                    for (const id of Object.keys(sampleAttrs)) {
                        expect(predicate(id)).toBe(true)
                    }
                })

                it('returns true while attributes have not loaded yet (avoid empty flash)', () => {
                    // Eval level + active filter, but attrs map is empty — attrs are in-flight
                    logic.actions.setClusteringLevel('evaluation')
                    logic.actions.setEvalEvaluatorNamesFilter(['Accuracy'])

                    // Any id — including ids that would later not match — is accepted in the loading state
                    expect(logic.values.evalFilterPredicate('any-id')).toBe(true)
                    expect(logic.values.evalFilterPredicate('id-fail-b')).toBe(true)
                })

                it('filters by evaluator name', () => {
                    setEvalLevelAndAttrs()
                    logic.actions.setEvalEvaluatorNamesFilter(['Accuracy'])

                    const predicate = logic.values.evalFilterPredicate
                    expect(predicate('id-pass-a')).toBe(true)
                    expect(predicate('id-pass-b')).toBe(true)
                    expect(predicate('id-fail-a')).toBe(true)
                    expect(predicate('id-fail-b')).toBe(false) // Relevance
                    expect(predicate('id-na-a')).toBe(false) // Relevance
                })

                it('filters by verdict', () => {
                    setEvalLevelAndAttrs()
                    logic.actions.setEvalVerdictsFilter(['pass', 'n/a'])

                    const predicate = logic.values.evalFilterPredicate
                    expect(predicate('id-pass-a')).toBe(true)
                    expect(predicate('id-pass-b')).toBe(true)
                    expect(predicate('id-fail-a')).toBe(false)
                    expect(predicate('id-fail-b')).toBe(false)
                    expect(predicate('id-na-a')).toBe(true)
                })

                it('combines evaluator-name and verdict filters with AND', () => {
                    setEvalLevelAndAttrs()
                    logic.actions.setEvalEvaluatorNamesFilter(['Accuracy'])
                    logic.actions.setEvalVerdictsFilter(['pass'])

                    const predicate = logic.values.evalFilterPredicate
                    expect(predicate('id-pass-a')).toBe(true)
                    expect(predicate('id-pass-b')).toBe(true)
                    expect(predicate('id-fail-a')).toBe(false) // Accuracy but fail
                    expect(predicate('id-fail-b')).toBe(false) // Relevance
                    expect(predicate('id-na-a')).toBe(false) // Relevance
                })

                it('rejects ids that are missing from attributes when filters are active', () => {
                    setEvalLevelAndAttrs()
                    logic.actions.setEvalEvaluatorNamesFilter(['Accuracy'])

                    expect(logic.values.evalFilterPredicate('unknown-id')).toBe(false)
                })
            })

            describe('filteredSortedClusters', () => {
                const buildTrace = (
                    id: string
                ): {
                    distance_to_centroid: number
                    rank: number
                    x: number
                    y: number
                    timestamp: string
                    trace_id: string
                    generation_id: string
                } => ({
                    distance_to_centroid: 0,
                    rank: 0,
                    x: 0,
                    y: 0,
                    timestamp: '2026-04-20T00:00:00Z',
                    trace_id: id,
                    generation_id: id,
                })
                const sampleClusters: Cluster[] = [
                    {
                        cluster_id: 0,
                        size: 3,
                        title: 'Accuracy cluster',
                        description: '',
                        traces: {
                            'id-pass-a': buildTrace('id-pass-a'),
                            'id-pass-b': buildTrace('id-pass-b'),
                            'id-fail-a': buildTrace('id-fail-a'),
                        },
                        centroid: [],
                        centroid_x: 0,
                        centroid_y: 0,
                    },
                    {
                        cluster_id: 1,
                        size: 2,
                        title: 'Relevance cluster',
                        description: '',
                        traces: {
                            'id-fail-b': buildTrace('id-fail-b'),
                            'id-na-a': buildTrace('id-na-a'),
                        },
                        centroid: [],
                        centroid_x: 0,
                        centroid_y: 0,
                    },
                ]

                const loadClustersAsCurrentRun = (): void => {
                    // filteredSortedClusters reads off the currentRun; seed a run and hydrate the cache.
                    logic.actions.loadClusteringRunSuccess({
                        runId: 'test-run',
                        clusters: sampleClusters,
                    } as ClusteringRun)
                }

                it('returns clusters unchanged when no filter is active', () => {
                    loadClustersAsCurrentRun()
                    setEvalLevelAndAttrs()

                    const result = logic.values.filteredSortedClusters
                    expect(result).toHaveLength(2)
                    const byId = Object.fromEntries(result.map((c) => [c.cluster_id, c]))
                    expect(byId[0].size).toBe(3)
                    expect(byId[1].size).toBe(2)
                })

                it('drops non-matching traces, rewrites size, and prunes clusters that empty out', () => {
                    loadClustersAsCurrentRun()
                    setEvalLevelAndAttrs()
                    logic.actions.setEvalVerdictsFilter(['pass'])

                    // Cluster 0 keeps its two pass traces; cluster 1's items are all fail/n/a so it's pruned.
                    const result = logic.values.filteredSortedClusters
                    expect(result).toHaveLength(1)
                    expect(result[0].cluster_id).toBe(0)
                    expect(Object.keys(result[0].traces).sort()).toEqual(['id-pass-a', 'id-pass-b'])
                    expect(result[0].size).toBe(2)
                })
            })
        })
    })
})
