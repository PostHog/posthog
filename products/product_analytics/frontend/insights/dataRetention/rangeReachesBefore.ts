import { type Dayjs, dayjs } from 'lib/dayjs'

import { isAnyDataWarehouseNode, isInsightQueryWithSeries, isInsightVizNode } from '~/queries/schema/node-guards'
import { Node } from '~/queries/schema/schema-general'

// Retention deletes only the events table, so an insight reading warehouse tables alone loses nothing.
export function readsOnlyWarehouseTables(source: Node | null | undefined): boolean {
    return (
        !!source &&
        isInsightQueryWithSeries(source) &&
        source.series.length > 0 &&
        source.series.every(isAnyDataWarehouseNode)
    )
}

export function rangeReachesBefore({
    query,
    resolvedDateFrom,
    cutoff,
}: {
    query?: Node | null
    resolvedDateFrom?: string | null
    cutoff: Dayjs | null
}): boolean {
    if (!cutoff || !resolvedDateFrom || readsOnlyWarehouseTables(isInsightVizNode(query) ? query.source : undefined)) {
        return false
    }
    return dayjs(resolvedDateFrom).isBefore(cutoff)
}
