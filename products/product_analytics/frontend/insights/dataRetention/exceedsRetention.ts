import { dayjs } from 'lib/dayjs'

import { Node } from '~/queries/schema/schema-general'
import {
    isAnyDataWarehouseNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightQueryWithSeries,
    isInsightVizNode,
} from '~/queries/utils'

/** Whether one insight's date range reaches past the team's events retention window.
 *
 * Shared by the per-insight banner, the dashboard-level banner and the tile icon so every surface answers the
 * question the same way, from the range the backend resolved for the results being shown.
 */
export function exceedsRetention({
    query,
    dateFromOverride,
    resolvedDateFrom,
    retentionMonths,
}: {
    query?: Node | null
    /** Effective range from a surface that overrides the query's own: a dashboard or tile filter, or the live editor. */
    dateFromOverride?: string | null
    /** `resolved_date_range.date_from` from the query response the surface is showing. */
    resolvedDateFrom?: string | null
    retentionMonths: number | null
}): boolean {
    if (!retentionMonths) {
        return false
    }
    // A SQL insight can scan arbitrary history and has no resolved range, so warn whenever retention applies.
    if (isHogQLQuery(query) || (isDataVisualizationNode(query) && isHogQLQuery(query.source))) {
        return true
    }
    const source = isInsightVizNode(query) ? query.source : undefined
    // Retention floors only the events table, so an insight reading warehouse tables alone can't be truncated.
    if (isInsightQueryWithSeries(source) && source.series.length > 0 && source.series.every(isAnyDataWarehouseNode)) {
        return false
    }
    const dateFrom = dateFromOverride ?? source?.dateRange?.date_from
    // "All time" resolves to the earliest event the floored query can still see, which is never older than the
    // window, so the resolved range alone can't reveal that older events were cut off.
    if (dateFrom === 'all') {
        return true
    }
    if (!resolvedDateFrom) {
        return false
    }
    return dayjs(resolvedDateFrom).isBefore(dayjs().subtract(retentionMonths, 'month'))
}
