import { useActions, useValues } from 'kea'

import { LemonButton, LemonInputSelect, LemonSwitch } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'

import { DateMappingOption } from '~/types'

import { endpointsUsageLogic } from './endpointsUsageLogic'

const endpointsUsageDateMapping: DateMappingOption[] = [
    {
        key: 'Last 24 hours',
        values: ['-24h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(24, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 48 hours',
        values: ['-48h'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(48, 'h'), date.endOf('d')),
        defaultInterval: 'hour',
    },
    {
        key: 'Last 7 days',
        values: ['-7d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(7, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 14 days',
        values: ['-14d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(14, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 30 days',
        values: ['-30d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(30, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Last 90 days',
        values: ['-90d'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.subtract(90, 'd'), date.endOf('d')),
        defaultInterval: 'day',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date.endOf('d')),
        defaultInterval: 'day',
    },
]

const RequestNameBreakdownToggle = ({ tabId }: { tabId: string }): JSX.Element => {
    const { requestNameBreakdownEnabled } = useValues(endpointsUsageLogic({ tabId }))
    const { setRequestNameBreakdownEnabled } = useActions(endpointsUsageLogic({ tabId }))

    return (
        <LemonButton
            onClick={() => setRequestNameBreakdownEnabled(!requestNameBreakdownEnabled)}
            type="secondary"
            size="small"
        >
            Breakdown by request name <LemonSwitch checked={requestNameBreakdownEnabled} className="ml-1" />
        </LemonButton>
    )
}

type RequestNameSelectProps = {
    value: string[]
    onChange: (values: string[]) => void
    tabId: string
}

const RequestNameFilter = ({ value, onChange, tabId }: RequestNameSelectProps): JSX.Element => {
    const { requestNames, requestNamesLoading } = useValues(endpointsUsageLogic({ tabId }))

    const options = requestNames.map((requestName: string) => ({
        key: requestName,
        label: requestName,
        value: requestName,
    }))

    return (
        <LemonInputSelect
            title="Request names"
            autoWidth={false}
            popoverClassName="max-h-60 max-w-s overflow-y-auto"
            className="max-h-30 max-w-s overflow-y-auto"
            value={value.map((v) => v.toString())}
            loading={requestNamesLoading}
            onChange={(newValues: string[]) => {
                const selectedRequestNames = requestNames.filter((requestName: string) =>
                    newValues.includes(requestName)
                )
                onChange(selectedRequestNames)
            }}
            mode="multiple"
            options={options}
            data-attr="request-names"
            bulkActions="select-and-clear-all"
            displayMode="count"
        />
    )
}

export const EndpointsUsageFilters = ({ tabs, tabId }: { tabs?: JSX.Element; tabId: string }): JSX.Element => {
    const { dateFilter, activeTab, requestNameFilter } = useValues(endpointsUsageLogic({ tabId }))
    const { setDates, setRequestNameFilter } = useActions(endpointsUsageLogic({ tabId }))

    return activeTab === 'usage' ? (
        <FilterBar
            className="m-0 px-0 rounded-none"
            top={tabs}
            left={
                <>
                    <DateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={setDates}
                        forceGranularity="day"
                        dateOptions={endpointsUsageDateMapping}
                    />
                    <RequestNameBreakdownToggle tabId={tabId} />
                    <RequestNameFilter value={requestNameFilter} onChange={setRequestNameFilter} tabId={tabId} />
                </>
            }
        />
    ) : (
        <></>
    )
}
