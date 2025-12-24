import api from 'lib/api'

import { hogql } from '~/queries/utils'

import { TraceSummary } from './types'

/**
 * Load trace summaries for a list of trace IDs.
 * Filters out IDs that already exist in existingSummaries to avoid redundant fetches.
 *
 * @param traceIds - List of trace IDs to load summaries for
 * @param existingSummaries - Already loaded summaries to skip
 * @param windowStart - ISO timestamp for filtering (required for ClickHouse efficiency)
 * @param windowEnd - ISO timestamp for filtering (required for ClickHouse efficiency)
 * @returns New summaries (only the ones that were missing)
 */
export async function loadTraceSummaries(
    traceIds: string[],
    existingSummaries: Record<string, TraceSummary>,
    windowStart: string,
    windowEnd: string
): Promise<Record<string, TraceSummary>> {
    const missingTraceIds = traceIds.filter((id) => !existingSummaries[id])

    if (missingTraceIds.length === 0) {
        return {}
    }

    const response = await api.queryHogQL(
        hogql`
            SELECT
                JSONExtractString(properties, '$ai_trace_id') as trace_id,
                argMax(JSONExtractString(properties, '$ai_summary_title'), timestamp) as title,
                argMax(JSONExtractString(properties, '$ai_summary_flow_diagram'), timestamp) as flow_diagram,
                argMax(JSONExtractString(properties, '$ai_summary_bullets'), timestamp) as bullets,
                argMax(JSONExtractString(properties, '$ai_summary_interesting_notes'), timestamp) as interesting_notes,
                max(timestamp) as timestamp
            FROM events
            WHERE event = '$ai_trace_summary'
                AND timestamp >= ${windowStart}
                AND timestamp <= ${windowEnd}
                AND JSONExtractString(properties, '$ai_trace_id') IN ${missingTraceIds}
            GROUP BY trace_id
            LIMIT 10000
        `,
        { productKey: 'llm_analytics', scene: 'LLMAnalyticsClusters' }
    )

    const summaries: Record<string, TraceSummary> = {}
    for (const row of response.results || []) {
        const r = row as string[]
        summaries[r[0]] = {
            traceId: r[0],
            title: r[1] || 'Untitled Trace',
            flowDiagram: r[2] || '',
            bullets: r[3] || '',
            interestingNotes: r[4] || '',
            timestamp: r[5],
        }
    }

    return summaries
}
