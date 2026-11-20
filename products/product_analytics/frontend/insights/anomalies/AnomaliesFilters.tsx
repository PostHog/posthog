import { useActions, useValues } from 'kea'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'

import { dashboardsModel } from '~/models/dashboardsModel'

import {
    SignalsAnomaliesSearchRetrieveInterval,
    SignalsAnomaliesSearchRetrieveOrder,
} from 'products/signals/frontend/generated/api.schemas'

import { ANOMALIES_DATE_RANGES } from './anomaliesDateRanges'
import { anomaliesTabLogic } from './anomaliesTabLogic'

const INTERVAL_OPTIONS: LemonSelectOptions<SignalsAnomaliesSearchRetrieveInterval | null> = [
    { value: null, label: 'All intervals' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Hour, label: 'Hourly' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Day, label: 'Daily' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Week, label: 'Weekly' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Month, label: 'Monthly' },
]

const ORDER_OPTIONS: LemonSelectOptions<SignalsAnomaliesSearchRetrieveOrder> = [
    { value: SignalsAnomaliesSearchRetrieveOrder.Recent, label: 'Most recent' },
    { value: SignalsAnomaliesSearchRetrieveOrder.Rate, label: 'Highest anomaly rate' },
]

export function AnomaliesFilters(): JSX.Element {
    const { filters } = useValues(anomaliesTabLogic)
    const { setFilters } = useActions(anomaliesTabLogic)
    const { nameSortedDashboards } = useValues(dashboardsModel)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonInput
                type="search"
                size="small"
                placeholder="Search insights"
                value={filters.search}
                onChange={(search) => setFilters({ search })}
                className="w-60"
                data-attr="anomalies-tab-search"
            />
            <LemonSelect
                size="small"
                value={filters.dateFrom}
                options={ANOMALIES_DATE_RANGES.map(({ dateFrom, label }) => ({ value: dateFrom, label }))}
                onChange={(dateFrom) => setFilters({ dateFrom })}
                data-attr="anomalies-tab-date-range"
            />
            <LemonSelect<SignalsAnomaliesSearchRetrieveInterval | null>
                size="small"
                value={filters.interval}
                options={INTERVAL_OPTIONS}
                onChange={(interval) => setFilters({ interval })}
                data-attr="anomalies-tab-interval"
            />
            <LemonSelect<number | null>
                size="small"
                value={filters.dashboardId}
                options={[
                    { value: null, label: 'All dashboards' },
                    ...nameSortedDashboards.map((dashboard) => ({
                        value: dashboard.id,
                        label: dashboard.name || 'Untitled dashboard',
                    })),
                ]}
                onChange={(dashboardId) => setFilters({ dashboardId })}
                dropdownMatchSelectWidth={false}
                data-attr="anomalies-tab-dashboard"
            />
            <LemonSelect
                size="small"
                value={filters.order}
                options={ORDER_OPTIONS}
                onChange={(order) => setFilters({ order })}
                data-attr="anomalies-tab-order"
            />
        </div>
    )
}
