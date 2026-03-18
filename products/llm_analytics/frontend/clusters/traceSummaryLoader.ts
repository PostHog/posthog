import api from 'lib/api'

import { hogql } from '~/queries/utils'

import { ClusteringLevel, TraceSummary } from './types'

/**
 * Load summaries for a list of item IDs (traces or generations).
 * Filters out IDs that already exist in existingSummaries to avoid redundant fetches.
 */
export async function loadTraceSummaries(
    itemIds: string[],
    existingSummaries: Record<string, TraceSummary>,
    windowStart: string,
    windowEnd: string,
    level: ClusteringLevel = 'trace'
): Promise<Record<string, TraceSummary>> {
    const missingItemIds = itemIds.filter((id) => !existingSummaries[id])

    if (missingItemIds.length === 0) {
        return {}
    }

    const eventName = level === 'generation' ? '$ai_generation_summary' : '$ai_trace_summary'
    const idProperty = level === 'generation' ? '$ai_generation_id' : '$ai_trace_id'

    const response = await api.queryHogQL(
        hogql`
            SELECT
                JSONExtractString(properties, ${idProperty}) as item_id,
                argMax(JSONExtractString(properties, '$ai_summary_title'), timestamp) as title,
                argMax(JSONExtractString(properties, '$ai_summary_flow_diagram'), timestamp) as flow_diagram,
                argMax(JSONExtractString(properties, '$ai_summary_bullets'), timestamp) as bullets,
                argMax(JSONExtractString(properties, '$ai_summary_interesting_notes'), timestamp) as interesting_notes,
                max(timestamp) as latest_timestamp,
                argMax(JSONExtractString(properties, '$ai_trace_id'), timestamp) as trace_id
            FROM events
            WHERE event = ${eventName}
                AND timestamp >= parseDateTimeBestEffort(${windowStart})
                AND timestamp <= parseDateTimeBestEffort(${windowEnd})
                AND JSONExtractString(properties, ${idProperty}) IN ${missingItemIds}
            GROUP BY item_id
            LIMIT 10000
        `,
        { productKey: 'llm_analytics', scene: 'LLMAnalyticsClusters' },
        // Window bounds are in UTC (from backend), so compare timestamps in UTC
        { queryParams: { modifiers: { convertToProjectTimezone: false } } }
    )

    const summaries: Record<string, TraceSummary> = {}
    for (const row of response.results || []) {
        const r = row as string[]
        const itemId = r[0]
        const traceId = r[6] || itemId // Fall back to item_id for trace-level

        summaries[itemId] = {
            traceId: traceId,
            generationId: level === 'generation' ? itemId : undefined,
            title: r[1] || (level === 'generation' ? 'Untitled Generation' : 'Untitled Trace'),
            flowDiagram: r[2] || '',
            bullets: r[3] || '',
            interestingNotes: r[4] || '',
            timestamp: r[5],
        }
    }

    return summaries
}
