import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import type { InsightSeriesGroup } from './anomaliesTabLogic'
import { AnomalyRow } from './AnomalyRow'

function seriesKey(series: AnomalySeriesApi): string {
    return `${series.insight_id}-${series.series_key}-${series.interval}`
}

export interface AnomalyInsightGroupProps {
    group: InsightSeriesGroup
    expanded: boolean
    dateFrom: string
    dateTo: string
    onToggleExpanded: () => void
    onOpenInsight: (series: AnomalySeriesApi) => void
}

export function AnomalyInsightGroup({
    group,
    expanded,
    dateFrom,
    dateTo,
    onToggleExpanded,
    onOpenInsight,
}: AnomalyInsightGroupProps): JSX.Element {
    const [topSeries, ...otherSeries] = group.series
    return (
        <div className="flex flex-col gap-2" data-attr="anomalies-tab-insight">
            <AnomalyRow
                series={topSeries}
                dateFrom={dateFrom}
                dateTo={dateTo}
                onOpenInsight={() => onOpenInsight(topSeries)}
            />
            {expanded && otherSeries.length > 0 && (
                <div className="flex flex-col gap-2 pl-4">
                    {otherSeries.map((series) => (
                        <AnomalyRow
                            key={seriesKey(series)}
                            series={series}
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            onOpenInsight={() => onOpenInsight(series)}
                        />
                    ))}
                </div>
            )}
            {otherSeries.length > 0 && (
                <div className="flex">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={onToggleExpanded}
                        data-attr="anomalies-tab-expand-insight"
                    >
                        {expanded ? 'Show fewer series' : `Show ${otherSeries.length} more flagged series`}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
