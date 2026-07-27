import { DateDisplay } from 'lib/components/DateDisplay'
import type { OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'
import type { IndexedTrendResult } from 'scenes/trends/types'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import { InsightActorsQuery, InsightVizNode, ResolvedDateRangeResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { IntervalType } from '~/types'

export interface TrendsChartClickDeps {
    context?: QueryContext<InsightVizNode>
    hasPersonsModal: boolean
    interval: IntervalType | null | undefined
    timezone: string
    weekStartDay: number | null | undefined
    resolvedDateRange: ResolvedDateRangeResponse | null | undefined
    querySource: InsightActorsQuery['source'] | null | undefined
    indexedResults: IndexedTrendResult[]
    // Injected so the adapter stays decoupled from PersonsModal's dep graph.
    openPersonsModal: (props: OpenPersonsModalProps) => void
}

/** Persons-modal overrides for the click handler. The default targets bar/line trends —
 *  actor rows show event count, are recordings-aware, and sort by event count desc.
 *  Lifecycle uses {@link LIFECYCLE_PERSONS_MODAL_OPTIONS}: the underlying actor query
 *  already carries the lifecycle `status` (via `datasetToActorsQuery`), so no extra
 *  columns or ordering are needed. */
export type TrendsPersonsModalOptions = Pick<OpenPersonsModalProps, 'additionalSelect' | 'orderBy'>

export const DEFAULT_PERSONS_MODAL_OPTIONS: TrendsPersonsModalOptions = {
    additionalSelect: {
        value_at_data_point: 'event_count',
        matched_recordings: 'matched_recordings',
    },
    orderBy: ['event_count DESC, actor_id DESC'],
}

export const LIFECYCLE_PERSONS_MODAL_OPTIONS: TrendsPersonsModalOptions = {
    additionalSelect: {},
    orderBy: undefined,
}

// Adapters key each hog-charts Series by `${r.id}`, so we can resolve back
// to the source IndexedTrendResult without stashing it on meta.
export function resolveDataset(seriesKey: string, indexedResults: IndexedTrendResult[]): IndexedTrendResult | null {
    return indexedResults.find((r) => String(r.id) === seriesKey) ?? null
}

export function handleTrendsChartClick(
    seriesKey: string,
    dataIndex: number,
    deps: TrendsChartClickDeps,
    personsModalOptions: TrendsPersonsModalOptions = DEFAULT_PERSONS_MODAL_OPTIONS
): void {
    const dataset = resolveDataset(seriesKey, deps.indexedResults)
    if (!dataset) {
        return
    }

    const day = dataset.action?.days?.[dataIndex] ?? dataset.days?.[dataIndex]
    if (day == null || day === '') {
        return
    }

    if (deps.context?.onDataPointClick) {
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

    const title = (actorLabel: string): JSX.Element => (
        <>
            {actorLabel} on{' '}
            <DateDisplay
                interval={deps.interval || 'day'}
                resolvedDateRange={deps.resolvedDateRange ?? undefined}
                timezone={deps.timezone}
                weekStartDay={deps.weekStartDay ?? undefined}
                date={day}
            />
        </>
    )

    deps.openPersonsModal({
        title,
        query: datasetToActorsQuery({ dataset, query: deps.querySource, day }),
        additionalSelect: personsModalOptions.additionalSelect,
        orderBy: personsModalOptions.orderBy,
    })
}
