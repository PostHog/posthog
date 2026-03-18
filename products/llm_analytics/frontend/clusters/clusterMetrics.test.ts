import { formatErrorRate, formatTokens } from '../utils'
import { ItemMetrics, aggregateClusterMetrics } from './clusterMetricsLoader'
import { Cluster } from './types'

function makeCluster(id: number, traceIds: string[]): Cluster {
    const traces: Cluster['traces'] = {}
    for (const traceId of traceIds) {
        traces[traceId] = { distance_to_centroid: 0, rank: 0, x: 0, y: 0, timestamp: '', trace_id: traceId }
    }
    return {
        cluster_id: id,
        size: traceIds.length,
        title: `Cluster ${id}`,
        description: '',
        traces,
        centroid: [],
        centroid_x: 0,
        centroid_y: 0,
    }
}

describe('cluster metrics', () => {
    describe('aggregateClusterMetrics', () => {
        it('returns null metrics when no items have data', () => {
            const cluster = makeCluster(0, ['t1', 't2'])
            const result = aggregateClusterMetrics([cluster], {})

            expect(result[0]).toEqual({
                avgCost: null,
                avgLatency: null,
                avgTokens: null,
                totalCost: null,
                errorRate: null,
                errorCount: 0,
                itemCount: 0,
            })
        })

        it('computes averages across items with data', () => {
            const cluster = makeCluster(0, ['t1', 't2', 't3'])
            const itemMetrics: Record<string, ItemMetrics> = {
                t1: { itemId: 't1', cost: 0.1, latency: 1.0, inputTokens: 100, outputTokens: 200, errorCount: 0 },
                t2: { itemId: 't2', cost: 0.2, latency: 2.0, inputTokens: 300, outputTokens: 400, errorCount: 1 },
            }

            const result = aggregateClusterMetrics([cluster], itemMetrics)

            expect(result[0].avgCost).toBeCloseTo(0.15)
            expect(result[0].avgLatency).toBeCloseTo(1.5)
            expect(result[0].avgTokens).toBeCloseTo(500)
            expect(result[0].totalCost).toBeCloseTo(0.3)
            expect(result[0].errorRate).toBeCloseTo(0.5)
            expect(result[0].errorCount).toBe(1)
            expect(result[0].itemCount).toBe(2)
        })

        it('skips null and zero values in averages', () => {
            const cluster = makeCluster(0, ['t1', 't2'])
            const itemMetrics: Record<string, ItemMetrics> = {
                t1: { itemId: 't1', cost: 0.1, latency: null, inputTokens: 0, outputTokens: 0, errorCount: 0 },
                t2: { itemId: 't2', cost: null, latency: 2.0, inputTokens: 500, outputTokens: 500, errorCount: 0 },
            }

            const result = aggregateClusterMetrics([cluster], itemMetrics)

            expect(result[0].avgCost).toBeCloseTo(0.1)
            expect(result[0].avgLatency).toBeCloseTo(2.0)
            expect(result[0].avgTokens).toBeCloseTo(1000)
            expect(result[0].totalCost).toBeCloseTo(0.1)
        })

        it('counts items with at least one error for error rate', () => {
            const cluster = makeCluster(0, ['t1', 't2', 't3'])
            const itemMetrics: Record<string, ItemMetrics> = {
                t1: {
                    itemId: 't1',
                    cost: null,
                    latency: null,
                    inputTokens: null,
                    outputTokens: null,
                    errorCount: 2,
                },
                t2: {
                    itemId: 't2',
                    cost: null,
                    latency: null,
                    inputTokens: null,
                    outputTokens: null,
                    errorCount: 3,
                },
                t3: {
                    itemId: 't3',
                    cost: null,
                    latency: null,
                    inputTokens: null,
                    outputTokens: null,
                    errorCount: 0,
                },
            }

            const result = aggregateClusterMetrics([cluster], itemMetrics)

            // 2 of 3 items have at least one error
            expect(result[0].errorCount).toBe(2)
            expect(result[0].errorRate).toBeCloseTo(2 / 3)
        })

        it('handles multiple clusters independently', () => {
            const cluster0 = makeCluster(0, ['t1'])
            const cluster1 = makeCluster(1, ['t2'])
            const itemMetrics: Record<string, ItemMetrics> = {
                t1: { itemId: 't1', cost: 0.1, latency: 1.0, inputTokens: 100, outputTokens: 100, errorCount: 0 },
                t2: { itemId: 't2', cost: 0.5, latency: 5.0, inputTokens: 1000, outputTokens: 1000, errorCount: 1 },
            }

            const result = aggregateClusterMetrics([cluster0, cluster1], itemMetrics)

            expect(result[0].avgCost).toBeCloseTo(0.1)
            expect(result[1].avgCost).toBeCloseTo(0.5)
            expect(result[0].errorCount).toBe(0)
            expect(result[1].errorCount).toBe(1)
        })

        it('returns empty object for empty clusters array', () => {
            expect(aggregateClusterMetrics([], {})).toEqual({})
        })
    })

    describe('formatTokens', () => {
        it.each([
            { input: 0, expected: '0' },
            { input: 500, expected: '500' },
            { input: 999, expected: '999' },
            { input: 1000, expected: '1.0k' },
            { input: 1500, expected: '1.5k' },
            { input: 99900, expected: '99.9k' },
            { input: 1000000, expected: '1.0M' },
            { input: 2500000, expected: '2.5M' },
        ])('formats $input as $expected', ({ input, expected }) => {
            expect(formatTokens(input)).toBe(expected)
        })
    })

    describe('formatErrorRate', () => {
        it.each([
            { input: 0, expected: '0%' },
            { input: 0.0005, expected: '<0.1%' },
            { input: 0.005, expected: '0.5%' },
            { input: 0.009, expected: '0.9%' },
            { input: 0.01, expected: '1%' },
            { input: 0.156, expected: '16%' },
            { input: 0.5, expected: '50%' },
            { input: 1.0, expected: '100%' },
        ])('formats $input as $expected', ({ input, expected }) => {
            expect(formatErrorRate(input)).toBe(expected)
        })
    })
})
