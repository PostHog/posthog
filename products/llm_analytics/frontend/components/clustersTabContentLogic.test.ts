import { expectLogic } from 'kea-test-utils'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'

import { NOISE_CLUSTER_ID } from '../clusters/constants'
import { Cluster } from '../clusters/types'
import { clustersTabContentLogic } from './clustersTabContentLogic'

jest.mock('~/lib/api')

describe('clustersTabContentLogic', () => {
    let logic: ReturnType<typeof clustersTabContentLogic.build>

    const mockCluster: Cluster = {
        cluster_id: 0,
        size: 10,
        title: 'Test Cluster',
        description: 'Test description',
        traces: {
            'trace-123': { distance_to_centroid: 0.1, rank: 0, x: 0.0, y: 0.0, timestamp: '2025-01-05T10:00:00Z' },
            'trace-456': { distance_to_centroid: 0.2, rank: 1, x: 0.1, y: 0.1, timestamp: '2025-01-05T11:00:00Z' },
        },
        centroid: [1.0],
        centroid_x: 0.05,
        centroid_y: 0.05,
    }

    const mockOutlierCluster: Cluster = {
        cluster_id: NOISE_CLUSTER_ID,
        size: 5,
        title: 'Outliers',
        description: 'Noise points',
        traces: {
            'trace-789': { distance_to_centroid: 0.9, rank: 0, x: 5.0, y: 5.0, timestamp: '2025-01-05T12:00:00Z' },
        },
        centroid: [],
        centroid_x: 5.0,
        centroid_y: 5.0,
    }

    const mockApi = api as jest.Mocked<typeof api>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    afterEach(() => {
        if (logic) {
            logic.unmount()
        }
    })

    describe('initialization', () => {
        it('uses traceId as key', () => {
            mockApi.queryHogQL = jest.fn().mockResolvedValue({ results: [] })

            logic = clustersTabContentLogic({ traceId: 'trace-123' })
            expect(logic.key).toBe('trace-123')
        })

        it('loads clusters on mount', async () => {
            mockApi.queryHogQL = jest.fn().mockResolvedValue({ results: [] })

            logic = clustersTabContentLogic({ traceId: 'trace-123' })
            logic.mount()

            await expectLogic(logic).toFinishAllListeners()

            expect(mockApi.queryHogQL).toHaveBeenCalled()
        })
    })

    describe('loaders', () => {
        describe('loadClusters', () => {
            it('returns empty array when no results', async () => {
                mockApi.queryHogQL = jest.fn().mockResolvedValue({ results: [] })

                logic = clustersTabContentLogic({ traceId: 'trace-123' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.clusters).toEqual([])
            })

            it('finds clusters containing the trace', async () => {
                mockApi.queryHogQL = jest.fn().mockResolvedValue({
                    results: [['run-1', JSON.stringify([mockCluster]), '2025-01-05T10:00:00Z']],
                })

                logic = clustersTabContentLogic({ traceId: 'trace-123' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.clusters).toHaveLength(1)
                expect(logic.values.clusters[0]).toMatchObject({
                    runId: 'run-1',
                    clusterId: 0,
                    clusterTitle: 'Test Cluster',
                    clusterSize: 10,
                    isOutlier: false,
                })
            })

            it('identifies outlier clusters correctly', async () => {
                mockApi.queryHogQL = jest.fn().mockResolvedValue({
                    results: [['run-1', JSON.stringify([mockOutlierCluster]), '2025-01-05T12:00:00Z']],
                })

                logic = clustersTabContentLogic({ traceId: 'trace-789' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.clusters).toHaveLength(1)
                expect(logic.values.clusters[0].isOutlier).toBe(true)
            })

            it('uses default title when cluster title is empty', async () => {
                const clusterWithoutTitle = { ...mockCluster, title: '' }
                mockApi.queryHogQL = jest.fn().mockResolvedValue({
                    results: [['run-1', JSON.stringify([clusterWithoutTitle]), '2025-01-05T10:00:00Z']],
                })

                logic = clustersTabContentLogic({ traceId: 'trace-123' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.clusters[0].clusterTitle).toBe('Cluster 0')
            })

            it('ignores clusters that do not contain the trace', async () => {
                mockApi.queryHogQL = jest.fn().mockResolvedValue({
                    results: [['run-1', JSON.stringify([mockCluster]), '2025-01-05T10:00:00Z']],
                })

                logic = clustersTabContentLogic({ traceId: 'trace-not-in-cluster' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.clusters).toEqual([])
            })

            it('finds traces across multiple runs', async () => {
                mockApi.queryHogQL = jest.fn().mockResolvedValue({
                    results: [
                        ['run-1', JSON.stringify([mockCluster]), '2025-01-05T10:00:00Z'],
                        ['run-2', JSON.stringify([mockCluster]), '2025-01-06T10:00:00Z'],
                    ],
                })

                logic = clustersTabContentLogic({ traceId: 'trace-123' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.clusters).toHaveLength(2)
                expect(logic.values.clusters[0].runId).toBe('run-1')
                expect(logic.values.clusters[1].runId).toBe('run-2')
            })

            it('handles malformed JSON gracefully', async () => {
                mockApi.queryHogQL = jest.fn().mockResolvedValue({
                    results: [
                        ['run-1', 'not valid json', '2025-01-05T10:00:00Z'],
                        ['run-2', JSON.stringify([mockCluster]), '2025-01-06T10:00:00Z'],
                    ],
                })

                logic = clustersTabContentLogic({ traceId: 'trace-123' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                // Should only include the valid result
                expect(logic.values.clusters).toHaveLength(1)
                expect(logic.values.clusters[0].runId).toBe('run-2')
            })

            it('handles null clusters JSON gracefully', async () => {
                mockApi.queryHogQL = jest.fn().mockResolvedValue({
                    results: [['run-1', null, '2025-01-05T10:00:00Z']],
                })

                logic = clustersTabContentLogic({ traceId: 'trace-123' })
                logic.mount()

                await expectLogic(logic).toFinishAllListeners()

                expect(logic.values.clusters).toEqual([])
            })
        })
    })

    describe('keyed logic instances', () => {
        it('creates separate instances for different traceIds', async () => {
            mockApi.queryHogQL = jest.fn().mockResolvedValue({ results: [] })

            const logic1 = clustersTabContentLogic({ traceId: 'trace-1' })
            const logic2 = clustersTabContentLogic({ traceId: 'trace-2' })

            expect(logic1.key).toBe('trace-1')
            expect(logic2.key).toBe('trace-2')
            expect(logic1).not.toBe(logic2)

            logic1.unmount()
            logic2.unmount()
        })
    })
})
