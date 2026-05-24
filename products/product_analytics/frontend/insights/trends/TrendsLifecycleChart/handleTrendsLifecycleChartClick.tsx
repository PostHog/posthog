import { DateDisplay } from 'lib/components/DateDisplay'
import { datasetToActorsQuery } from 'scenes/trends/viz/datasetToActorsQuery'

import { resolveDataset, type TrendsChartClickDeps } from '../shared/handleTrendsChartClick'

// Lifecycle is the only trends mode whose persons modal uses `additionalSelect: {}` and
// `orderBy: undefined`. The actor query carries the lifecycle `status` (via
// datasetToActorsQuery), so no extra event_count / matched_recordings columns are needed.
export function handleTrendsLifecycleChartClick(
    seriesKey: string,
    dataIndex: number,
    deps: TrendsChartClickDeps
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
        additionalSelect: {},
        orderBy: undefined,
    })
}
