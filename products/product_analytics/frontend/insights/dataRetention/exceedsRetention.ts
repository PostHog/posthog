import { type Dayjs, dayjs } from 'lib/dayjs'

import {
    isAnyDataWarehouseNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightQueryWithSeries,
    isInsightVizNode,
} from '~/queries/schema/node-guards'
import { InsightVizNode, Node } from '~/queries/schema/schema-general'

// Retention floors and deletes only the events table, so an insight reading warehouse tables alone loses nothing.
export function readsOnlyWarehouseTables(source: Node | null | undefined): boolean {
    return (
        !!source &&
        isInsightQueryWithSeries(source) &&
        source.series.length > 0 &&
        source.series.every(isAnyDataWarehouseNode)
    )
}

function insightSource(query: Node | null | undefined): InsightVizNode['source'] | undefined {
    return isInsightVizNode(query) ? query.source : undefined
}

interface InsightRange {
    query?: Node | null
    /** Effective range from a surface that overrides the query's own: a dashboard or tile filter, or the live editor. */
    dateFromOverride?: string | null
    /** `resolved_date_range.date_from` from the query response the surface is showing. */
    resolvedDateFrom?: string | null
}

/** Whether one insight's date range reaches back before `cutoff`.
 *
 * Shared by the per-insight banner, the dashboard-level banner and the tile icon so every surface answers the
 * question the same way, from the range the backend resolved for the results being shown.
 */
export function rangeReachesBefore({
    query,
    resolvedDateFrom,
    cutoff,
}: InsightRange & { cutoff: Dayjs | null }): boolean {
    if (!cutoff || readsOnlyWarehouseTables(insightSource(query))) {
        return false
    }
    // A SQL insight can scan arbitrary history and has no resolved range, so warn whenever retention applies.
    if (isHogQLQuery(query) || (isDataVisualizationNode(query) && isHogQLQuery(query.source))) {
        return true
    }
    return !!resolvedDateFrom && dayjs(resolvedDateFrom).isBefore(cutoff)
}

export function exceedsRetention({
    retentionMonths,
    ...range
}: InsightRange & { retentionMonths: number | null }): boolean {
    if (!retentionMonths) {
        return false
    }
    const source = insightSource(range.query)
    // "All time" resolves to the earliest event the floored query can still see, which is never older than the
    // window, so the resolved range alone can't reveal that older events were cut off.
    if ((range.dateFromOverride ?? source?.dateRange?.date_from) === 'all') {
        return !readsOnlyWarehouseTables(source)
    }
    return rangeReachesBefore({ ...range, cutoff: dayjs().subtract(retentionMonths, 'month') })
}
