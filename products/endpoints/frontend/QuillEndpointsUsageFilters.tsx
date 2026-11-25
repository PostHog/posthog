import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconRefresh } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
} from '@posthog/quill'

import { EndpointsUsageBreakdown } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { endpointsUsageLogic } from './endpointsUsageLogic'
import { QuillEndpointsUsageDateFilter } from './QuillEndpointsUsageDateFilter'

type MaterializationType = 'materialized' | 'inline'

// Radio rows hold strings, and "no choice" has no string of its own.
const NONE = 'none'
type OrNone<T extends string> = T | typeof NONE

const EXECUTION_TYPE_OPTIONS: FilterOption<OrNone<MaterializationType>>[] = [
    { value: NONE, label: 'All execution types' },
    { value: 'materialized', label: 'Materialized executions' },
    { value: 'inline', label: 'Direct executions' },
]

const BREAKDOWN_OPTIONS: FilterOption<OrNone<EndpointsUsageBreakdown>>[] = [
    { value: NONE, label: 'No breakdown' },
    { value: EndpointsUsageBreakdown.Endpoint, label: 'By endpoint' },
    { value: EndpointsUsageBreakdown.MaterializationType, label: 'By execution type' },
    { value: EndpointsUsageBreakdown.ApiKey, label: 'By personal API key' },
    { value: EndpointsUsageBreakdown.Status, label: 'By status' },
]

const INTERVAL_OPTIONS: FilterOption<IntervalType>[] = [
    { value: 'hour', label: 'Hourly' },
    { value: 'day', label: 'Daily' },
    { value: 'week', label: 'Weekly' },
    { value: 'month', label: 'Monthly' },
]

/** The endpoint filter stays visible because the "View usage" links set it, so a person sees what the page is scoped to. */
const EndpointNameFilter = (): JSX.Element => {
    const { endpointNames, endpointNamesLoading, endpointFilter } = useValues(endpointsUsageLogic)
    const { setEndpointFilter } = useActions(endpointsUsageLogic)
    const triggerRef = useRef<HTMLButtonElement>(null)

    const label =
        endpointFilter.length === 0
            ? 'All endpoints'
            : endpointFilter.length === 1
              ? endpointFilter[0]
              : `${endpointFilter.length} endpoints`

    return (
        <Combobox
            multiple
            items={endpointNames}
            value={endpointFilter}
            onValueChange={(names: string[]) => setEndpointFilter(names)}
        >
            <ComboboxTrigger
                ref={triggerRef}
                render={<Button variant="outline" className="max-w-72 justify-between" />}
                data-attr="endpoint-names-filter"
            >
                <span className="truncate">{label}</span>
            </ComboboxTrigger>
            <ComboboxContent anchor={triggerRef} align="start" className="w-80">
                <ComboboxInput placeholder="Search endpoints" showTrigger={false} />
                <ComboboxEmpty>{endpointNamesLoading ? 'Loading endpoints…' : 'No endpoints match'}</ComboboxEmpty>
                <ComboboxList>
                    {(name: string) => (
                        <ComboboxItem key={name} value={name} title={name}>
                            <span className="truncate">{name}</span>
                        </ComboboxItem>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}

/** The execution type filter and the chart choices in one menu, so the row never wraps into a column of selects. */
const UsageFilterMenu = (): JSX.Element => {
    const { materializationType, breakdownBy, interval } = useValues(endpointsUsageLogic)
    const { setMaterializationType, setBreakdownBy, setInterval } = useActions(endpointsUsageLogic)
    const active = materializationType !== null

    return (
        <DropdownMenu>
            <FilterMenuTrigger active={active} dataAttr="endpoints-usage-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
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
                    label="Break down by"
                    options={BREAKDOWN_OPTIONS}
                    value={breakdownBy ?? NONE}
                    onChange={(next) => setBreakdownBy(next === NONE ? null : next)}
                    dataAttr="breakdown-filter"
                />
                <FilterRadioSubMenu
                    label="Interval"
                    options={INTERVAL_OPTIONS}
                    value={interval}
                    onChange={setInterval}
                    dataAttr="interval-filter"
                />
                <FilterClearItem
                    active={active}
                    onClear={() => setMaterializationType(null)}
                    dataAttr="endpoints-usage-filter-clear"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

const RefreshButton = (): JSX.Element => {
    const { canRefresh } = useValues(endpointsUsageLogic)
    const { refresh } = useActions(endpointsUsageLogic)

    return (
        <Button
            variant="outline"
            onClick={refresh}
            tooltip="Refresh usage data"
            disabledReason={
                !canRefresh
                    ? 'You can refresh once every 15 minutes. Note that it is not realtime, and may be delayed a few minutes.'
                    : undefined
            }
            data-attr="endpoints-usage-refresh"
        >
            <IconRefresh />
            Refresh
        </Button>
    )
}

export const QuillEndpointsUsageFilters = (): JSX.Element => {
    return (
        <div className="flex flex-wrap items-center gap-2">
            <QuillEndpointsUsageDateFilter />
            <EndpointNameFilter />
            <UsageFilterMenu />
            <div className="ml-auto">
                <RefreshButton />
            </div>
        </div>
    )
}
