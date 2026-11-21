import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { type AnomalyRowRating, type InsightSeriesGroup, anomalyRatingKey, anomalySeriesKey } from './anomaliesTabLogic'
import { AnomalyRow } from './AnomalyRow'

export interface AnomalyInsightGroupProps {
    group: InsightSeriesGroup
    expanded: boolean
    dateFrom: string
    dateTo: string
    seriesRatings: Record<string, AnomalyRowRating>
    onToggleExpanded: () => void
    onOpenInsight: (series: AnomalySeriesApi) => void
    onRateSeries: (series: AnomalySeriesApi, rating: AnomalyRowRating) => void
    onCreateAlert: (series: AnomalySeriesApi) => void
}

export function AnomalyInsightGroup({
    group,
    expanded,
    dateFrom,
    dateTo,
    seriesRatings,
    onToggleExpanded,
    onOpenInsight,
    onRateSeries,
    onCreateAlert,
}: AnomalyInsightGroupProps): JSX.Element {
    const [topSeries, ...otherSeries] = group.series
    return (
        <div className="flex flex-col gap-2" data-attr="anomalies-tab-insight">
            <AnomalyRow
                series={topSeries}
                dateFrom={dateFrom}
                dateTo={dateTo}
                rating={seriesRatings[anomalyRatingKey(topSeries)]}
                onOpenInsight={() => onOpenInsight(topSeries)}
                onRate={(rating) => onRateSeries(topSeries, rating)}
                onCreateAlert={() => onCreateAlert(topSeries)}
            />
            {expanded && otherSeries.length > 0 && (
                <div className="flex flex-col gap-2 pl-4">
                    {otherSeries.map((series) => (
                        <AnomalyRow
                            key={anomalySeriesKey(series)}
                            series={series}
                            dateFrom={dateFrom}
                            dateTo={dateTo}
                            rating={seriesRatings[anomalyRatingKey(series)]}
                            onOpenInsight={() => onOpenInsight(series)}
                            onRate={(rating) => onRateSeries(series, rating)}
                            onCreateAlert={() => onCreateAlert(series)}
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
                        {expanded ? 'Show fewer series' : `Show ${otherSeries.length} more anomalous series`}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
