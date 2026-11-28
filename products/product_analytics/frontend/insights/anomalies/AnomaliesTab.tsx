import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { AnomaliesEmptyState } from './AnomaliesEmptyState'
import { AnomaliesFilters } from './AnomaliesFilters'
import { SCORED_HISTORY_READY_DAYS, anomaliesTabLogic, anomalyRatingKey, anomalySeriesKey } from './anomaliesTabLogic'
import { AnomalyChartLegend } from './AnomalyChartLegend'
import { AnomalyRow } from './AnomalyRow'

function SeriesCappedBanner(): JSX.Element {
    return (
        <div data-attr="anomalies-tab-series-capped">
            <LemonBanner type="warning">
                This search found more series than it can read at once, so some anomalies may be missing. Narrow the
                date range or the filters to see them all.
            </LemonBanner>
        </div>
    )
}

function ScopeFallbackBanner({ viewedWithinDays }: { viewedWithinDays: number }): JSX.Element {
    return (
        <div data-attr="anomalies-tab-scope-fallback">
            <LemonBanner type="info">
                {`You haven't viewed any insights or dashboards with insights in the last ${viewedWithinDays} days, so this list shows the whole project.`}
            </LemonBanner>
        </div>
    )
}

export function AnomaliesTab(): JSX.Element {
    const { anomalies, anomaliesLoading, loadingMore, loadError, series, hasMore, seriesRatings } =
        useValues(anomaliesTabLogic)
    const { loadAnomalies, loadMoreAnomalies, reportInsightOpened, rateSeries, reportCreateAlertOpened } =
        useActions(anomaliesTabLogic)

    const reloading = anomaliesLoading && !loadingMore

    return (
        <div className="flex flex-col gap-4">
            <p className="text-secondary m-0">
                Saved trends insights with anomalous values, checked automatically. No setup needed.
            </p>
            <AnomaliesFilters />

            {loadError === 'not_available' ? (
                <EmptyMessage
                    title="Anomalies aren't available for this project yet"
                    description="Anomaly search isn't turned on for this project."
                />
            ) : loadError === 'failed' ? (
                <EmptyMessage
                    title="Couldn't load anomalies"
                    description="Try again, and if it keeps happening contact support."
                    buttonText="Try again"
                    buttonOnClick={() => loadAnomalies()}
                    buttonDataAttr="anomalies-tab-retry"
                />
            ) : reloading || !anomalies ? (
                <div className="flex flex-col gap-2">
                    {Array.from({ length: 3 }, (_, index) => (
                        <LemonSkeleton key={index} className="h-52 w-full" />
                    ))}
                </div>
            ) : series.length === 0 ? (
                <>
                    {anomalies.viewed_scope_empty && anomalies.viewed_within_days != null && (
                        <ScopeFallbackBanner viewedWithinDays={anomalies.viewed_within_days} />
                    )}
                    {anomalies.series_capped && <SeriesCappedBanner />}
                    <AnomaliesEmptyState anomalies={anomalies} />
                </>
            ) : (
                <>
                    {!anomalies.scored_history_ready && (
                        <LemonBanner type="info">
                            {`This project has ${anomalies.scored_days} of ${SCORED_HISTORY_READY_DAYS} days of scored history. Until it has ${SCORED_HISTORY_READY_DAYS}, anomaly results are less reliable.`}
                        </LemonBanner>
                    )}
                    {anomalies.viewed_scope_empty && anomalies.viewed_within_days != null && (
                        <ScopeFallbackBanner viewedWithinDays={anomalies.viewed_within_days} />
                    )}
                    {anomalies.series_capped && <SeriesCappedBanner />}
                    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-secondary text-sm">
                        <div data-attr="anomalies-tab-coverage">
                            <span>
                                {`${anomalies.insights_scored_in_range} of ${anomalies.watched_insights} watched insights checked in this range`}
                            </span>
                            {anomalies.scored_through && (
                                <>
                                    <span> · Checked through </span>
                                    <TZLabel time={anomalies.scored_through} />
                                </>
                            )}
                        </div>
                        <AnomalyChartLegend />
                    </div>
                    <div className="flex flex-col gap-2">
                        {series.map((row, index) => (
                            <AnomalyRow
                                key={anomalySeriesKey(row)}
                                series={row}
                                // A weekly or monthly series can be checked over a longer range than the requested one.
                                dateFrom={
                                    anomalies.interval_ranges.find((range) => range.interval === row.interval)
                                        ?.date_from ?? anomalies.date_from
                                }
                                dateTo={anomalies.date_to}
                                rating={seriesRatings[anomalyRatingKey(row)]}
                                onOpenInsight={() => reportInsightOpened(row, index)}
                                onRate={(rating) => rateSeries(row, rating, index)}
                                onCreateAlert={() => reportCreateAlertOpened(row, index)}
                            />
                        ))}
                    </div>
                    {hasMore && (
                        <div className="flex justify-center">
                            <LemonButton
                                type="secondary"
                                loading={loadingMore}
                                onClick={() => loadMoreAnomalies()}
                                data-attr="anomalies-tab-load-more"
                            >
                                Load more
                            </LemonButton>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
