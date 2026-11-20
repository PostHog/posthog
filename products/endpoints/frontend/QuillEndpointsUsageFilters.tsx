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
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { EndpointsUsageBreakdown } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { endpointsUsageLogic } from './endpointsUsageLogic'
import { QuillEndpointsUsageDateFilter } from './QuillEndpointsUsageDateFilter'

type MaterializationType = 'materialized' | 'inline'

// A Select value is a string, so "all" stands in for the logic's null.
const ALL_EXECUTION_TYPES = 'all'
const EXECUTION_TYPE_LABELS: Record<MaterializationType | typeof ALL_EXECUTION_TYPES, string> = {
    all: 'All execution types',
    materialized: 'Materialized executions',
    inline: 'Direct executions',
}

const INTERVAL_OPTIONS: { value: IntervalType; label: string }[] = [
    { value: 'hour', label: 'Hourly' },
    { value: 'day', label: 'Daily' },
    { value: 'week', label: 'Weekly' },
    { value: 'month', label: 'Monthly' },
]

const NO_BREAKDOWN = 'none'
const BREAKDOWN_LABELS: Record<EndpointsUsageBreakdown | typeof NO_BREAKDOWN, string> = {
    none: 'No breakdown',
    [EndpointsUsageBreakdown.Endpoint]: 'By endpoint',
    [EndpointsUsageBreakdown.MaterializationType]: 'By execution type',
    [EndpointsUsageBreakdown.ApiKey]: 'By personal API key',
    [EndpointsUsageBreakdown.Status]: 'By status',
}

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

const MaterializationTypeFilter = (): JSX.Element => {
    const { materializationType } = useValues(endpointsUsageLogic)
    const { setMaterializationType } = useActions(endpointsUsageLogic)

    return (
        <Select
            value={materializationType ?? ALL_EXECUTION_TYPES}
            onValueChange={(value: string | null) =>
                value && setMaterializationType(value === ALL_EXECUTION_TYPES ? null : (value as MaterializationType))
            }
        >
            <SelectTrigger data-attr="materialization-type-filter">
                <SelectValue>
                    {(value: MaterializationType | typeof ALL_EXECUTION_TYPES) => EXECUTION_TYPE_LABELS[value]}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {Object.entries(EXECUTION_TYPE_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                        {label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

const IntervalFilter = (): JSX.Element => {
    const { interval } = useValues(endpointsUsageLogic)
    const { setInterval } = useActions(endpointsUsageLogic)

    return (
        <Select value={interval} onValueChange={(value: string | null) => value && setInterval(value as IntervalType)}>
            <SelectTrigger data-attr="interval-filter">
                <SelectValue>
                    {(value: IntervalType) => INTERVAL_OPTIONS.find((option) => option.value === value)?.label}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                {INTERVAL_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

const BreakdownFilter = (): JSX.Element => {
    const { breakdownBy } = useValues(endpointsUsageLogic)
    const { setBreakdownBy } = useActions(endpointsUsageLogic)

    return (
        <Select
            value={breakdownBy ?? NO_BREAKDOWN}
            onValueChange={(value: string | null) =>
                value && setBreakdownBy(value === NO_BREAKDOWN ? null : (value as EndpointsUsageBreakdown))
            }
        >
            <SelectTrigger data-attr="breakdown-filter">
                <SelectValue>
                    {(value: EndpointsUsageBreakdown | typeof NO_BREAKDOWN) => BREAKDOWN_LABELS[value]}
                </SelectValue>
            </SelectTrigger>
            <SelectContent align="end" alignItemWithTrigger={false}>
                {Object.entries(BREAKDOWN_LABELS).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                        {label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
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
            <MaterializationTypeFilter />
            <div className="ml-auto flex flex-wrap items-center gap-2">
                <IntervalFilter />
                <BreakdownFilter />
                <RefreshButton />
            </div>
        </div>
    )
}
