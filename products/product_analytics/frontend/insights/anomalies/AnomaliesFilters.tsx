import { useActions, useValues } from 'kea'

import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect, LemonSelectOptions } from 'lib/lemon-ui/LemonSelect'

import {
    SignalsAnomaliesSearchRetrieveInterval,
    SignalsAnomaliesSearchRetrieveViewedWithinDays,
} from 'products/signals/frontend/generated/api.schemas'

import { AnomaliesDashboardPicker } from './AnomaliesDashboardPicker'
import { ANOMALIES_DATE_RANGES } from './anomaliesDateRanges'
import { AnomaliesScope, anomaliesTabLogic } from './anomaliesTabLogic'

const INTERVAL_OPTIONS: LemonSelectOptions<SignalsAnomaliesSearchRetrieveInterval | null> = [
    { value: null, label: 'All intervals' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Hour, label: 'Hourly' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Day, label: 'Daily' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Week, label: 'Weekly' },
    { value: SignalsAnomaliesSearchRetrieveInterval.Month, label: 'Monthly' },
]

const SCOPE_OPTIONS: LemonSelectOptions<AnomaliesScope> = [
    ...Object.values(SignalsAnomaliesSearchRetrieveViewedWithinDays).map((days) => ({
        value: days,
        label: `Viewed by me, last ${days} days`,
    })),
    { value: null, label: 'Whole project' },
]

export function AnomaliesFilters(): JSX.Element {
    const { filters } = useValues(anomaliesTabLogic)
    const { setFilters } = useActions(anomaliesTabLogic)

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
            <LemonSelect<AnomaliesScope>
                size="small"
                value={filters.viewedWithinDays}
                options={SCOPE_OPTIONS}
                onChange={(viewedWithinDays) => setFilters({ viewedWithinDays })}
                data-attr="anomalies-tab-scope"
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
            <AnomaliesDashboardPicker />
        </div>
    )
}
