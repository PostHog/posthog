import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
} from '@posthog/quill'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { EndpointsUsageBreakdown } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { endpointsUsageDateMapping } from './endpointsUsageDateMapping'
import { endpointsUsageLogic } from './endpointsUsageLogic'

// Radio rows hold strings, and "no choice" has no string of its own.
const NONE = 'none'
type OrNone<T extends string> = T | typeof NONE

const BREAKDOWN_OPTIONS: FilterOption<OrNone<EndpointsUsageBreakdown>>[] = [
    { value: NONE, label: 'No breakdown' },
    { value: EndpointsUsageBreakdown.Endpoint, label: 'By endpoint' },
    { value: EndpointsUsageBreakdown.MaterializationType, label: 'By execution type' },
    { value: EndpointsUsageBreakdown.ApiKey, label: 'By personal API key' },
    { value: EndpointsUsageBreakdown.Status, label: 'By status' },
]

const EXECUTION_TYPE_OPTIONS: FilterOption<OrNone<'materialized' | 'inline'>>[] = [
    { value: NONE, label: 'All execution types' },
    { value: 'materialized', label: 'Materialized executions' },
    { value: 'inline', label: 'Direct executions' },
]

const INTERVAL_OPTIONS: FilterOption<IntervalType>[] = [
    { value: 'hour', label: 'Hourly' },
    { value: 'day', label: 'Daily' },
    { value: 'week', label: 'Weekly' },
    { value: 'month', label: 'Monthly' },
]

/** Chart grouping and the two filters in one menu, so the row never wraps into a column of selects. */
function UsageFilterMenu(): JSX.Element {
    const { endpointNames, endpointNamesLoading, endpointFilter, materializationType, breakdownBy, interval } =
        useValues(endpointsUsageLogic)
    const { setEndpointFilter, setMaterializationType, setBreakdownBy, setInterval } = useActions(endpointsUsageLogic)
    const active = endpointFilter.length > 0 || materializationType !== null

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={active} dataAttr="endpoints-usage-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterRadioSubMenu
                    label="Break down by"
                    options={BREAKDOWN_OPTIONS}
                    value={breakdownBy ?? NONE}
                    onChange={(next) => setBreakdownBy(next === NONE ? null : (next as EndpointsUsageBreakdown))}
                    dataAttr="breakdown-filter"
                />
                <DropdownMenuSeparator />
                <FilterSearchSubMenu
                    label="Endpoints"
                    allLabel="All endpoints"
                    pluralNoun="endpoints"
                    options={endpointNames.map((name) => ({ value: name, label: name }))}
                    selected={endpointFilter}
                    onChange={setEndpointFilter}
                    loading={endpointNamesLoading}
                    searchPlaceholder="Search endpoints"
                    emptyText="No matching endpoints"
                    dataAttr="endpoint-names-filter"
                />
                <FilterRadioSubMenu
                    label="Execution type"
                    options={EXECUTION_TYPE_OPTIONS}
                    value={materializationType ?? NONE}
                    defaultValue={NONE}
                    onChange={(next) => setMaterializationType(next === NONE ? null : next)}
                    dataAttr="materialization-type-filter"
                />
                <DropdownMenuSeparator />
                <FilterRadioSubMenu
                    label="Interval"
                    options={INTERVAL_OPTIONS}
                    value={interval}
                    onChange={setInterval}
                    dataAttr="interval-filter"
                />
                <FilterClearItem
                    active={active}
                    onClear={() => {
                        setEndpointFilter([])
                        setMaterializationType(null)
                    }}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function UsageRefreshButton(): JSX.Element {
    const { canRefresh } = useValues(endpointsUsageLogic)
    const { refresh } = useActions(endpointsUsageLogic)

    return (
        <Button
            variant="outline"
            tooltip="Refresh usage data."
            disabledReason={
                !canRefresh
                    ? 'You can refresh once every 15 minutes. Note that it is not realtime, and may be delayed a few minutes.'
                    : undefined
            }
            onClick={refresh}
            aria-label="Refresh usage data"
            data-attr="endpoints-usage-refresh"
        >
            <IconRefresh />
            Refresh
        </Button>
    )
}

export function QuillEndpointsUsageFilters(): JSX.Element {
    const { dateFilter } = useValues(endpointsUsageLogic)
    const { setDates } = useActions(endpointsUsageLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <DateFilter
                dateFrom={dateFilter.dateFrom}
                dateTo={dateFilter.dateTo}
                onChange={setDates}
                forceGranularity="day"
                dateOptions={endpointsUsageDateMapping}
            />
            <UsageFilterMenu />
            <div className="ml-auto">
                <UsageRefreshButton />
            </div>
        </div>
    )
}
