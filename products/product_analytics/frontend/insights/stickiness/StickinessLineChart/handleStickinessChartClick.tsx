import type { IndexedTrendResult } from '@posthog/query-frontend/nodes/TrendsQuery/types'
import { datasetToActorsQuery } from '@posthog/query-frontend/nodes/TrendsQuery/viz/datasetToActorsQuery'
import type { OpenPersonsModalProps } from '@posthog/query-frontend/persons-modal/PersonsModal'
import { InsightActorsQuery, InsightVizNode } from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import { IntervalType } from '~/types'

export interface StickinessChartClickDeps {
    context?: QueryContext<InsightVizNode>
    hasPersonsModal: boolean
    interval: IntervalType | null | undefined
    querySource: InsightActorsQuery['source'] | null | undefined
    indexedResults: IndexedTrendResult[]
    // Injected so the adapter stays decoupled from PersonsModal's dep graph.
    openPersonsModal: (props: OpenPersonsModalProps) => void
}

function resolveDataset(seriesKey: string, indexedResults: IndexedTrendResult[]): IndexedTrendResult | null {
    return indexedResults.find((r) => String(r.id) === seriesKey) ?? null
}

export function handleStickinessChartClick(seriesKey: string, dataIndex: number, deps: StickinessChartClickDeps): void {
    const dataset = resolveDataset(seriesKey, deps.indexedResults)
    if (!dataset) {
        return
    }

    const day = dataset.action?.days?.[dataIndex] ?? dataset.days?.[dataIndex]
    if (day == null || day === '') {
        return
    }

    if (deps.context?.onDataPointClick) {
        // Intentional behavior change from legacy ActionsLineGraph: that code path
        // passed `dataset.breakdownValues?.[index]` which on stickiness `IndexedTrendResult`
        // was always `undefined`. We surface `dataset.breakdown_value` instead so
        // consumers see the actual breakdown value the user clicked.
        deps.context.onDataPointClick(
            {
                breakdown: dataset.breakdown_value,
                compare: dataset.compare_label || undefined,
                day,
            },
            // Legacy parity with ActionsLineGraph — passes the first result, not the clicked one.
            deps.indexedResults[0]
        )
        return
    }

    if (!deps.hasPersonsModal || !deps.querySource) {
        return
    }

    const label = dataset.label ?? ''
    const title = (
        <>
            <PropertyKeyInfo value={label} disablePopover /> stickiness on {deps.interval || 'day'} {day}
        </>
    )

    deps.openPersonsModal({
        title,
        query: datasetToActorsQuery({ dataset, query: deps.querySource, day }),
        additionalSelect: {},
        orderBy: undefined,
    })
}
