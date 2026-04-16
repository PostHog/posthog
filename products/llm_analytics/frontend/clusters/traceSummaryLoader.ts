import api from 'lib/api'

import { hogql } from '~/queries/utils'

import { ClusteringLevel, TraceSummary } from './types'

/**
 * Load summaries for a list of item IDs (traces or generations) — or, for
 * evaluation-level clusters, load the underlying $ai_evaluation events and
 * adapt them into the same TraceSummary shape the UI renders.
 *
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

    if (level === 'evaluation') {
        return loadEvaluationSummaries(missingItemIds, windowStart, windowEnd)
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

/**
 * Eval cluster members don't have $ai_*_summary events — the cluster item ids
 * are the $ai_evaluation event UUIDs themselves. Fetch those rows directly and
 * render them into the TraceSummary shape so `ClusterTraceList` can reuse the
 * same rendering pipeline: title = "{evaluator_name}: {verdict}", reasoning
 * goes in the expandable bullets slot, generationId points at the linked
 * generation so the "View generation" link works.
 */
async function loadEvaluationSummaries(
    evalIds: string[],
    windowStart: string,
    windowEnd: string
): Promise<Record<string, TraceSummary>> {
    // Cluster members can include eval events from Stage B's embedding lookback,
    // which extends a few days past the UI's run-day window. Widen by 7 days on
    // the leading edge so we catch all members while still pruning partitions.
    const response = await api.queryHogQL(
        hogql`
            SELECT
                toString(uuid) as eval_id,
                JSONExtractString(properties, '$ai_evaluation_name') as name,
                JSONExtractString(properties, '$ai_evaluation_result') as result,
                JSONExtractString(properties, '$ai_evaluation_applicable') as applicable,
                JSONExtractString(properties, '$ai_evaluation_reasoning') as reasoning,
                JSONExtractString(properties, '$ai_evaluation_runtime') as runtime,
                JSONExtractString(properties, '$ai_target_event_id') as target_generation_id,
                JSONExtractString(properties, '$ai_trace_id') as trace_id,
                timestamp
            FROM events
            WHERE event = '$ai_evaluation'
                AND timestamp >= parseDateTimeBestEffort(${windowStart}) - INTERVAL 7 DAY
                AND timestamp <= parseDateTimeBestEffort(${windowEnd}) + INTERVAL 1 DAY
                AND toString(uuid) IN ${evalIds}
            LIMIT 10000
        `,
        { productKey: 'llm_analytics', scene: 'LLMAnalyticsClusters' },
        { queryParams: { modifiers: { convertToProjectTimezone: false } } }
    )

    const summaries: Record<string, TraceSummary> = {}
    for (const row of response.results || []) {
        const r = row as (string | null)[]
        const evalId = r[0] as string
        if (!evalId) {
            continue
        }
        const verdict = deriveVerdict(r[2], r[3])
        const name = r[1] || 'Evaluation'
        summaries[evalId] = {
            traceId: r[7] || '',
            generationId: r[6] || undefined, // link target is the linked generation, not the eval
            // Title is just the evaluator name — the display components render
            // the verdict separately as a LemonTag and don't need it duplicated
            // in the title.
            title: name,
            flowDiagram: '',
            // Put the reasoning text in the "bullets" slot so the existing toggle renders it.
            bullets: r[4] ? `- ${r[4]}` : '',
            interestingNotes: '',
            timestamp: (r[8] as string) ?? '',
            evaluationVerdict: verdict,
            evaluationReasoning: r[4] || undefined,
            evaluationRuntime: r[5] || undefined,
        }
    }
    return summaries
}

function deriveVerdict(result: string | null, applicable: string | null): 'pass' | 'fail' | 'n/a' | 'unknown' {
    const a = (applicable || '').toLowerCase()
    if (a === 'false') {
        return 'n/a'
    }
    const v = (result || '').toLowerCase()
    if (v === 'true') {
        return 'pass'
    }
    if (v === 'false') {
        return 'fail'
    }
    return 'unknown'
}
