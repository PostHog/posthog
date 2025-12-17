import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { clustersLogic } from './clustersLogic'
import { Cluster, ClusteringRun, NOISE_CLUSTER_ID } from './types'

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
    })

    describe('selectors', () => {
        const mockCluster1: Cluster = {
            cluster_id: 0,
            size: 10,
            title: 'Cluster A',
            description: 'Description A',
            traces: {
                'trace-1': { distance_to_centroid: 0.1, rank: 0, x: 0.0, y: 0.0, timestamp: '2025-01-05T10:00:00Z' },
                'trace-2': { distance_to_centroid: 0.2, rank: 1, x: 0.1, y: 0.1, timestamp: '2025-01-05T11:00:00Z' },
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
                'trace-3': { distance_to_centroid: 0.1, rank: 0, x: 1.0, y: 1.0, timestamp: '2025-01-05T12:00:00Z' },
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
                'trace-noise-1': { distance_to_centroid: 0.9, rank: 0, x: 5.0, y: 5.0, timestamp: '' },
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
                    totalTracesAnalyzed: 30,
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
                    totalTracesAnalyzed: 15,
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
                    totalTracesAnalyzed: 10,
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
                    totalTracesAnalyzed: 15,
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
                    totalTracesAnalyzed: 15,
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
                    totalTracesAnalyzed: 15,
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
                    totalTracesAnalyzed: 10,
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
    })
})
