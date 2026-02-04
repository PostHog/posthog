import api from 'lib/api'

import { hogql } from '~/queries/utils'

import { Cluster, ClusterMetrics, ClusteringLevel } from './types'

interface ItemMetrics {
    itemId: string
    cost: number | null
    latency: number | null
    inputTokens: number | null
    outputTokens: number | null
    isError: boolean
}

/**
 * Load metrics (cost, latency, tokens) for items in clusters.
 * Returns a map of cluster_id -> ClusterMetrics with averages computed.
 */
export async function loadClusterMetrics(
    clusters: Cluster[],
    windowStart: string,
    windowEnd: string,
    level: ClusteringLevel = 'trace'
): Promise<Record<number, ClusterMetrics>> {
    // Collect all item IDs from all clusters
    const allItemIds: string[] = []
    const itemToCluster: Record<string, number> = {}

    for (const cluster of clusters) {
        for (const itemId of Object.keys(cluster.traces)) {
            allItemIds.push(itemId)
            itemToCluster[itemId] = cluster.cluster_id
        }
    }

    if (allItemIds.length === 0) {
        return {}
    }

    // For trace-level, query $ai_trace events; for generation-level, query $ai_generation events
    const eventName = level === 'generation' ? '$ai_generation' : '$ai_trace'
    const idProperty = level === 'generation' ? '$ai_generation_id' : '$ai_trace_id'

    // Query for metrics from the actual trace/generation events
    // Error detection: $ai_error is set (non-empty, non-null) OR $ai_is_error is true
    const response = await api.queryHogQL(
        hogql`
            SELECT
                JSONExtractString(properties, ${idProperty}) as item_id,
                toFloat64OrNull(JSONExtractRaw(properties, '$ai_total_cost_usd')) as cost,
                toFloat64OrNull(JSONExtractRaw(properties, '$ai_latency')) as latency,
                toInt64OrNull(JSONExtractRaw(properties, '$ai_input_tokens')) as input_tokens,
                toInt64OrNull(JSONExtractRaw(properties, '$ai_output_tokens')) as output_tokens,
                (
                    (JSONExtractRaw(properties, '$ai_error') != '' AND JSONExtractRaw(properties, '$ai_error') != 'null')
                    OR JSONExtractBool(properties, '$ai_is_error') = true
                ) as is_error
            FROM events
            WHERE event = ${eventName}
                AND timestamp >= parseDateTimeBestEffort(${windowStart})
                AND timestamp <= parseDateTimeBestEffort(${windowEnd})
                AND JSONExtractString(properties, ${idProperty}) IN ${allItemIds}
            LIMIT 50000
        `,
        { productKey: 'llm_analytics', scene: 'LLMAnalyticsClusters' },
        // Window bounds are in UTC (from backend), so compare timestamps in UTC
        { queryParams: { modifiers: { convertToProjectTimezone: false } } }
    )

    // Build a map of itemId -> metrics
    const itemMetrics: Record<string, ItemMetrics> = {}
    for (const row of response.results || []) {
        const r = row as (string | number | boolean | null)[]
        const itemId = r[0] as string
        if (itemId) {
            itemMetrics[itemId] = {
                itemId,
                cost: r[1] as number | null,
                latency: r[2] as number | null,
                inputTokens: r[3] as number | null,
                outputTokens: r[4] as number | null,
                isError: Boolean(r[5]),
            }
        }
    }

    // Aggregate metrics per cluster
    const clusterMetrics: Record<number, ClusterMetrics> = {}

    for (const cluster of clusters) {
        let totalCost = 0
        let totalLatency = 0
        let totalTokens = 0
        let costCount = 0
        let latencyCount = 0
        let tokenCount = 0
        let errorCount = 0
        let totalItemsWithData = 0

        for (const itemId of Object.keys(cluster.traces)) {
            const metrics = itemMetrics[itemId]
            if (metrics) {
                totalItemsWithData++
                if (metrics.isError) {
                    errorCount++
                }
                if (metrics.cost !== null && metrics.cost > 0) {
                    totalCost += metrics.cost
                    costCount++
                }
                if (metrics.latency !== null && metrics.latency > 0) {
                    totalLatency += metrics.latency
                    latencyCount++
                }
                const tokens = (metrics.inputTokens || 0) + (metrics.outputTokens || 0)
                if (tokens > 0) {
                    totalTokens += tokens
                    tokenCount++
                }
            }
        }

        clusterMetrics[cluster.cluster_id] = {
            avgCost: costCount > 0 ? totalCost / costCount : null,
            avgLatency: latencyCount > 0 ? totalLatency / latencyCount : null,
            avgTokens: tokenCount > 0 ? totalTokens / tokenCount : null,
            totalCost: costCount > 0 ? totalCost : null,
            errorRate: totalItemsWithData > 0 ? errorCount / totalItemsWithData : null,
            errorCount,
            itemCount: Math.max(costCount, latencyCount, tokenCount, totalItemsWithData),
        }
    }

    return clusterMetrics
}
