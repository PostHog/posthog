import { useActions, useValues } from 'kea'

import { LemonInputSelect, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FilterBar } from 'lib/components/FilterBar'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils'

import { EndpointsUsageBreakdown } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'
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

const EndpointNameFilter = ({ tabId }: { tabId: string }): JSX.Element => {
    const { endpointNames, endpointNamesLoading, endpointFilter } = useValues(endpointsUsageLogic({ tabId }))
    const { setEndpointFilter } = useActions(endpointsUsageLogic({ tabId }))

    const options = endpointNames.map((name: string) => ({
        key: name,
        label: name,
        value: name,
    }))

    return (
        <LemonInputSelect
            title="Endpoints"
            autoWidth={false}
            popoverClassName="max-h-60 max-w-s overflow-y-auto"
            className="max-h-30 max-w-s overflow-y-auto"
            value={endpointFilter.map((v) => v.toString())}
            loading={endpointNamesLoading}
            onChange={(newValues: string[]) => {
                const selectedEndpoints = endpointNames.filter((name: string) => newValues.includes(name))
                setEndpointFilter(selectedEndpoints)
            }}
            mode="multiple"
            options={options}
            data-attr="endpoint-names-filter"
            bulkActions="select-and-clear-all"
            displayMode="count"
            placeholder="All endpoints"
        />
    )
}

const MaterializationTypeFilter = ({ tabId }: { tabId: string }): JSX.Element => {
    const { materializationType } = useValues(endpointsUsageLogic({ tabId }))
    const { setMaterializationType } = useActions(endpointsUsageLogic({ tabId }))

    return (
        <LemonSelect
            value={materializationType}
            onChange={setMaterializationType}
            options={[
                { value: null, label: 'All execution types' },
                { value: 'materialized', label: 'Materialized executions' },
                { value: 'inline', label: 'Direct executions' },
            ]}
            data-attr="materialization-type-filter"
            size="small"
            dropdownPlacement="bottom-end"
        />
    )
}

const IntervalFilter = ({ tabId }: { tabId: string }): JSX.Element => {
    const { interval } = useValues(endpointsUsageLogic({ tabId }))
    const { setInterval } = useActions(endpointsUsageLogic({ tabId }))

    return (
        <LemonSelect
            value={interval}
            onChange={setInterval}
            options={[
                { value: 'hour' as IntervalType, label: 'Hourly' },
                { value: 'day' as IntervalType, label: 'Daily' },
                { value: 'week' as IntervalType, label: 'Weekly' },
                { value: 'month' as IntervalType, label: 'Monthly' },
            ]}
            data-attr="interval-filter"
            size="small"
            dropdownPlacement="bottom-end"
        />
    )
}

const BreakdownFilter = ({ tabId }: { tabId: string }): JSX.Element => {
    const { breakdownBy } = useValues(endpointsUsageLogic({ tabId }))
    const { setBreakdownBy } = useActions(endpointsUsageLogic({ tabId }))

    return (
        <LemonSelect
            value={breakdownBy}
            onChange={setBreakdownBy}
            options={[
                { value: null, label: 'No breakdown' },
                { value: EndpointsUsageBreakdown.Endpoint, label: 'By endpoint' },
                { value: EndpointsUsageBreakdown.MaterializationType, label: 'By execution type' },
                { value: EndpointsUsageBreakdown.ApiKey, label: 'By API key' },
                { value: EndpointsUsageBreakdown.Status, label: 'By status' },
            ]}
            data-attr="breakdown-filter"
            size="small"
            dropdownPlacement="bottom-end"
        />
    )
}

export const EndpointsUsageFilters = ({ tabId }: { tabId: string }): JSX.Element => {
    const { dateFilter } = useValues(endpointsUsageLogic({ tabId }))
    const { setDates } = useActions(endpointsUsageLogic({ tabId }))

    return (
        <FilterBar
            className="m-0 px-0 rounded-none"
            left={
                <>
                    <DateFilter
                        dateFrom={dateFilter.dateFrom}
                        dateTo={dateFilter.dateTo}
                        onChange={setDates}
                        forceGranularity="day"
                        dateOptions={endpointsUsageDateMapping}
                    />
                    <EndpointNameFilter tabId={tabId} />
                </>
            }
            right={
                <>
                    <MaterializationTypeFilter tabId={tabId} />
                    <IntervalFilter tabId={tabId} />
                    <BreakdownFilter tabId={tabId} />
                </>
            }
        />
    )
}
