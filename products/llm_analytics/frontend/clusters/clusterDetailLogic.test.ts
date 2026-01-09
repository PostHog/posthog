import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { clusterDetailLogic } from './clusterDetailLogic'
import { NOISE_CLUSTER_ID, TRACES_PER_PAGE } from './constants'
import { Cluster } from './types'

describe('clusterDetailLogic', () => {
    let logic: ReturnType<typeof clusterDetailLogic.build>

    const mockCluster: Cluster = {
        cluster_id: 0,
        size: 100,
        title: 'Test Cluster',
        description: 'Test cluster description',
        traces: {
            'trace-1': { distance_to_centroid: 0.1, rank: 0, x: 0.0, y: 0.0, timestamp: '2025-01-05T10:00:00Z' },
            'trace-2': { distance_to_centroid: 0.2, rank: 1, x: 0.1, y: 0.1, timestamp: '2025-01-05T11:00:00Z' },
            'trace-3': { distance_to_centroid: 0.3, rank: 2, x: 0.2, y: 0.2, timestamp: '2025-01-05T12:00:00Z' },
        },
        centroid: [1.0],
        centroid_x: 0.1,
        centroid_y: 0.1,
    }

    const mockOutlierCluster: Cluster = {
        ...mockCluster,
        cluster_id: NOISE_CLUSTER_ID,
        title: 'Outliers',
    }

    beforeEach(() => {
        initKeaTests()
        logic = clusterDetailLogic({ runId: 'test_2025-01-05', clusterId: 0 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('reducers', () => {
        describe('currentPage', () => {
            it('defaults to page 1', () => {
                expect(logic.values.currentPage).toBe(1)
            })

            it('updates page via setPage action', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setPage(2)
                }).toMatchValues({
                    currentPage: 2,
                })
            })
        })

        describe('traceSummaries', () => {
            it('defaults to empty object', () => {
                expect(logic.values.traceSummaries).toEqual({})
            })

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

        describe('traceSummariesLoading', () => {
            it('defaults to false', () => {
                expect(logic.values.traceSummariesLoading).toBe(false)
            })

            it('updates loading state', async () => {
                await expectLogic(logic, () => {
                    logic.actions.setTraceSummariesLoading(true)
                }).toMatchValues({
                    traceSummariesLoading: true,
                })

                await expectLogic(logic, () => {
                    logic.actions.setTraceSummariesLoading(false)
                }).toMatchValues({
                    traceSummariesLoading: false,
                })
            })
        })
    })

    describe('selectors', () => {
        describe('cluster', () => {
            it('returns null when clusterData is null', () => {
                expect(logic.values.cluster).toBeNull()
            })

            it('returns cluster when clusterData is loaded', async () => {
                logic.actions.loadClusterDataSuccess({
                    cluster: mockCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                expect(logic.values.cluster).toEqual(mockCluster)
            })
        })

        describe('isOutlierCluster', () => {
            it('returns false for regular cluster', async () => {
                logic.actions.loadClusterDataSuccess({
                    cluster: mockCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                expect(logic.values.isOutlierCluster).toBe(false)
            })

            it('returns true for outlier cluster', async () => {
                logic.actions.loadClusterDataSuccess({
                    cluster: mockOutlierCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                expect(logic.values.isOutlierCluster).toBe(true)
            })
        })

        describe('sortedTraceIds', () => {
            it('returns empty array when no cluster', () => {
                expect(logic.values.sortedTraceIds).toEqual([])
            })

            it('returns trace IDs sorted by rank', async () => {
                logic.actions.loadClusterDataSuccess({
                    cluster: mockCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                expect(logic.values.sortedTraceIds).toEqual(['trace-1', 'trace-2', 'trace-3'])
            })
        })

        describe('totalTraces', () => {
            it('returns 0 when no cluster', () => {
                expect(logic.values.totalTraces).toBe(0)
            })

            it('returns number of traces in cluster', async () => {
                logic.actions.loadClusterDataSuccess({
                    cluster: mockCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                expect(logic.values.totalTraces).toBe(3)
            })
        })

        describe('totalPages', () => {
            it('calculates pages correctly', async () => {
                const largeCluster: Cluster = {
                    ...mockCluster,
                    traces: Object.fromEntries(
                        Array.from({ length: 120 }, (_, i) => [
                            `trace-${i}`,
                            { distance_to_centroid: 0.1, rank: i, x: 0, y: 0, timestamp: '' },
                        ])
                    ),
                }

                logic.actions.loadClusterDataSuccess({
                    cluster: largeCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                expect(logic.values.totalPages).toBe(Math.ceil(120 / TRACES_PER_PAGE))
            })
        })

        describe('paginatedTraceIds', () => {
            it('returns first page of traces', async () => {
                const largeCluster: Cluster = {
                    ...mockCluster,
                    traces: Object.fromEntries(
                        Array.from({ length: 100 }, (_, i) => [
                            `trace-${i}`,
                            { distance_to_centroid: 0.1, rank: i, x: 0, y: 0, timestamp: '' },
                        ])
                    ),
                }

                logic.actions.loadClusterDataSuccess({
                    cluster: largeCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                expect(logic.values.paginatedTraceIds.length).toBe(TRACES_PER_PAGE)
                expect(logic.values.paginatedTraceIds[0]).toBe('trace-0')
            })

            it('returns correct page when page is changed', async () => {
                const largeCluster: Cluster = {
                    ...mockCluster,
                    traces: Object.fromEntries(
                        Array.from({ length: 100 }, (_, i) => [
                            `trace-${i}`,
                            { distance_to_centroid: 0.1, rank: i, x: 0, y: 0, timestamp: '' },
                        ])
                    ),
                }

                logic.actions.loadClusterDataSuccess({
                    cluster: largeCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                logic.actions.setPage(2)

                expect(logic.values.paginatedTraceIds[0]).toBe(`trace-${TRACES_PER_PAGE}`)
            })
        })

        describe('paginatedTracesWithSummaries', () => {
            it('returns empty array when no cluster', () => {
                expect(logic.values.paginatedTracesWithSummaries).toEqual([])
            })

            it('returns traces with summaries attached', async () => {
                logic.actions.loadClusterDataSuccess({
                    cluster: mockCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                const summary = {
                    'trace-1': {
                        traceId: 'trace-1',
                        title: 'Summary Title',
                        flowDiagram: '',
                        bullets: '',
                        interestingNotes: '',
                        timestamp: '',
                    },
                }
                logic.actions.setTraceSummaries(summary)

                const result = logic.values.paginatedTracesWithSummaries
                expect(result[0].traceId).toBe('trace-1')
                expect(result[0].summary).toEqual(summary['trace-1'])
                expect(result[1].summary).toBeUndefined()
            })
        })

        describe('breadcrumbs', () => {
            it('generates correct breadcrumbs', async () => {
                logic.actions.loadClusterDataSuccess({
                    cluster: mockCluster,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                const breadcrumbs = logic.values.breadcrumbs
                expect(breadcrumbs).toHaveLength(4)
                expect(breadcrumbs[0].name).toBe('LLM analytics')
                expect(breadcrumbs[1].name).toBe('Clusters')
                expect(breadcrumbs[3].name).toBe('Test Cluster')
            })

            it('uses default cluster name when cluster has no title', async () => {
                const clusterWithoutTitle = { ...mockCluster, title: '' }
                logic.actions.loadClusterDataSuccess({
                    cluster: clusterWithoutTitle,
                    runTimestamp: '2025-01-05T00:00:00Z',
                    windowStart: '2025-01-01T00:00:00Z',
                    windowEnd: '2025-01-05T00:00:00Z',
                })

                const breadcrumbs = logic.values.breadcrumbs
                expect(breadcrumbs[3].name).toBe('Cluster')
            })
        })
    })
})
