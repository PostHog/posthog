import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { AnomaliesEmptyState } from './AnomaliesEmptyState'
import { AnomaliesFilters } from './AnomaliesFilters'
import { SCORED_HISTORY_READY_DAYS, anomaliesTabLogic } from './anomaliesTabLogic'
import { AnomalyInsightGroup } from './AnomalyInsightGroup'

export function AnomaliesTab(): JSX.Element {
    const {
        anomalies,
        anomaliesLoading,
        loadingMore,
        loadError,
        series,
        insightGroups,
        expandedInsightIds,
        hasMore,
        seriesRatings,
    } = useValues(anomaliesTabLogic)
    const {
        loadAnomalies,
        loadMoreAnomalies,
        reportInsightOpened,
        toggleInsightExpanded,
        rateSeries,
        reportCreateAlertOpened,
    } = useActions(anomaliesTabLogic)

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
                        <LemonSkeleton key={index} className="h-36 w-full" />
                    ))}
                </div>
            ) : series.length === 0 ? (
                <AnomaliesEmptyState anomalies={anomalies} />
            ) : (
                <>
                    {!anomalies.scored_history_ready && (
                        <LemonBanner type="info">
                            {`This project has ${anomalies.scored_days} of ${SCORED_HISTORY_READY_DAYS} days of scored history. Until it has ${SCORED_HISTORY_READY_DAYS}, anomaly results are less reliable.`}
                        </LemonBanner>
                    )}
                    {anomalies.series_capped && (
                        <div data-attr="anomalies-tab-series-capped">
                            <LemonBanner type="warning">
                                This search found more series than it can read at once, so some anomalies may be
                                missing. Narrow the date range or the filters to see them all.
                            </LemonBanner>
                        </div>
                    )}
                    <div className="text-secondary text-sm" data-attr="anomalies-tab-coverage">
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
                    <div className="flex flex-col gap-2">
                        {insightGroups.map((group, index) => (
                            <AnomalyInsightGroup
                                key={group.insightId}
                                group={group}
                                expanded={!!expandedInsightIds[group.insightId]}
                                dateFrom={anomalies.date_from}
                                dateTo={anomalies.date_to}
                                seriesRatings={seriesRatings}
                                onToggleExpanded={() => toggleInsightExpanded(group.insightId, index)}
                                onOpenInsight={(row) => reportInsightOpened(row, index)}
                                onRateSeries={(row, rating) => rateSeries(row, rating, index)}
                                onCreateAlert={(row) => reportCreateAlertOpened(row, index)}
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
