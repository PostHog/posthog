import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { AnomalySearchResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { anomaliesDateRangeLabel, longerAnomaliesDateRange } from './anomaliesDateRanges'
import { SCORED_HISTORY_READY_DAYS, anomaliesTabLogic } from './anomaliesTabLogic'

export interface AnomaliesEmptyStateProps {
    anomalies: AnomalySearchResponseApi
}

export function AnomaliesEmptyState({ anomalies }: AnomaliesEmptyStateProps): JSX.Element {
    const { filters } = useValues(anomaliesTabLogic)
    const { setFilters, resetFilters } = useActions(anomaliesTabLogic)

    if (!anomalies.scoring_enabled) {
        return (
            <EmptyMessage
                title="Anomaly scoring is off for this project"
                description={anomalies.message ?? 'No insight in this project is checked for anomalies.'}
            />
        )
    }

    if (!anomalies.scored_history_ready) {
        return (
            <EmptyMessage
                title="Anomaly scoring is still building history"
                description={`Scoring needs ${SCORED_HISTORY_READY_DAYS} days of history before its flags are reliable. This project has ${anomalies.scored_days} so far.`}
            />
        )
    }

    const checked = `${anomalies.insights_scored_in_range} of ${filters.mine ? 'your ' : ''}${anomalies.watched_insights} watched insights were checked.`
    if (filters.search.trim() || filters.dashboardId != null) {
        return (
            <EmptyMessage
                title="No flagged series match these filters"
                description={checked}
                buttonText="Clear filters"
                buttonOnClick={resetFilters}
                buttonDataAttr="anomalies-tab-clear-filters"
            />
        )
    }

    const longerRange = longerAnomaliesDateRange(filters.dateFrom)
    const rangeLabel = anomaliesDateRangeLabel(filters.dateFrom).toLowerCase()
    if (filters.mine) {
        // EmptyMessage takes one button, and this state offers two ways to widen the search.
        return (
            <div className="flex flex-col items-center justify-center gap-2 m-5 text-center">
                <h3 className="m-0">{`Nothing was flagged in your insights in the ${rangeLabel}`}</h3>
                <p className="text-secondary m-0">{`Your insights are the ones you created or viewed in the last 90 days. ${checked}`}</p>
                <div className="flex flex-wrap justify-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => setFilters({ mine: false })}
                        data-attr="anomalies-tab-show-everyones"
                    >
                        Show everyone's
                    </LemonButton>
                    {longerRange && (
                        <LemonButton
                            type="secondary"
                            onClick={() => setFilters({ dateFrom: longerRange.dateFrom })}
                            data-attr="anomalies-tab-longer-range"
                        >
                            Try a longer range
                        </LemonButton>
                    )}
                </div>
            </div>
        )
    }

    return (
        <EmptyMessage
            title={`Nothing unusual in the ${rangeLabel}`}
            description={checked}
            buttonText={longerRange ? 'Try a longer range' : undefined}
            buttonOnClick={longerRange ? () => setFilters({ dateFrom: longerRange.dateFrom }) : undefined}
            buttonDataAttr="anomalies-tab-longer-range"
        />
    )
}
