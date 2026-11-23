import { useActions, useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { pluralize } from 'lib/utils/strings'

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
                description={`Scoring needs ${SCORED_HISTORY_READY_DAYS} days of history before its anomaly results are reliable. This project has ${anomalies.scored_days} so far.`}
            />
        )
    }

    const checked = `${anomalies.insights_scored_in_range} of ${anomalies.watched_insights} watched insights were checked.`
    if (filters.search.trim() || filters.dashboardId != null) {
        return (
            <EmptyMessage
                title="No anomalous series match these filters"
                description={checked}
                buttonText="Clear filters"
                buttonOnClick={resetFilters}
                buttonDataAttr="anomalies-tab-clear-filters"
            />
        )
    }

    const longerRange = longerAnomaliesDateRange(filters.dateFrom)
    if (anomalies.insights_scored_in_range === 0) {
        return (
            <EmptyMessage
                title="No insights were checked in this range"
                description={`Scoring checks ${pluralize(anomalies.watched_insights, 'watched insight')} a few at a time, and none of them was scored in this range. There is no result yet on whether any of them was anomalous.`}
                buttonText={longerRange ? 'Try a longer range' : undefined}
                buttonOnClick={longerRange ? () => setFilters({ dateFrom: longerRange.dateFrom }) : undefined}
                buttonDataAttr="anomalies-tab-longer-range"
            />
        )
    }

    return (
        <EmptyMessage
            title={`No anomalies in the ${anomaliesDateRangeLabel(filters.dateFrom).toLowerCase()}`}
            description={checked}
            buttonText={longerRange ? 'Try a longer range' : undefined}
            buttonOnClick={longerRange ? () => setFilters({ dateFrom: longerRange.dateFrom }) : undefined}
            buttonDataAttr="anomalies-tab-longer-range"
        />
    )
}
