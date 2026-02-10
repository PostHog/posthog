import api from 'lib/api'

import { hogql } from '~/queries/utils'

import { Cluster, ClusterMetrics, ClusteringLevel } from './types'

export interface ItemMetrics {
    itemId: string
    cost: number | null
    latency: number | null
    inputTokens: number | null
    outputTokens: number | null
    errorCount: number
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

    for (const cluster of clusters) {
        for (const itemId of Object.keys(cluster.traces)) {
            allItemIds.push(itemId)
        }
    }

    if (allItemIds.length === 0) {
        return {}
    }

    // For generation-level clustering, cluster keys are $ai_generation event UUIDs so match directly.
    // For trace-level clustering, aggregate metrics across all AI events in the trace
    // (generations, embeddings, spans) grouped by trace ID.
    const isGeneration = level === 'generation'

    const response = await api.queryHogQL(
        isGeneration
            ? hogql`
                SELECT
                    toString(uuid) as item_id,
                    toFloat(properties.$ai_total_cost_usd) as cost,
                    toFloat(properties.$ai_latency) as latency,
                    toInt(properties.$ai_input_tokens) as input_tokens,
                    toInt(properties.$ai_output_tokens) as output_tokens,
                    if(properties.$ai_is_error = 'true', 1, 0) as error_count
                FROM events
                WHERE event = '$ai_generation'
                    AND timestamp >= parseDateTimeBestEffort(${windowStart})
                    AND timestamp <= parseDateTimeBestEffort(${windowEnd})
                    AND toString(uuid) IN ${allItemIds}
                LIMIT ${allItemIds.length}
            `
            : hogql`
                SELECT
                    JSONExtractString(properties, '$ai_trace_id') as item_id,
                    sum(toFloat(properties.$ai_total_cost_usd)) as cost,
                    max(toFloat(properties.$ai_latency)) as latency,
                    sum(toInt(properties.$ai_input_tokens)) as input_tokens,
                    sum(toInt(properties.$ai_output_tokens)) as output_tokens,
                    countIf(properties.$ai_is_error = 'true') as error_count
                FROM events
                WHERE event IN ('$ai_generation', '$ai_embedding', '$ai_span')
                    AND timestamp >= parseDateTimeBestEffort(${windowStart})
                    AND timestamp <= parseDateTimeBestEffort(${windowEnd})
                    AND JSONExtractString(properties, '$ai_trace_id') IN ${allItemIds}
                GROUP BY item_id
                LIMIT ${allItemIds.length}
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
                errorCount: (r[5] as number) || 0,
            }
        }
    }

    return aggregateClusterMetrics(clusters, itemMetrics)
}

export function aggregateClusterMetrics(
    clusters: Cluster[],
    itemMetrics: Record<string, ItemMetrics>
): Record<number, ClusterMetrics> {
    const clusterMetrics: Record<number, ClusterMetrics> = {}

    for (const cluster of clusters) {
        let totalCost = 0
        let totalLatency = 0
        let totalTokens = 0
        let costCount = 0
        let latencyCount = 0
        let tokenCount = 0
        let itemsWithErrors = 0
        let totalItemsWithData = 0

        for (const itemId of Object.keys(cluster.traces)) {
            const metrics = itemMetrics[itemId]
            if (metrics) {
                totalItemsWithData++
                if (metrics.errorCount > 0) {
                    itemsWithErrors++
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
            errorRate: totalItemsWithData > 0 ? itemsWithErrors / totalItemsWithData : null,
            errorCount: itemsWithErrors,
            itemCount: totalItemsWithData,
        }
    }

    return clusterMetrics
}
