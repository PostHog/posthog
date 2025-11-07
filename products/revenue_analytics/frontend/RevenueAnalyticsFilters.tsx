import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconGraph, IconLineGraph, IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOptions, Popover, Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { FilterBar } from 'lib/components/FilterBar'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isRevenueAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { IconAreaChart, IconWithCount } from 'lib/lemon-ui/icons'
import { DATE_FORMAT, formatDateRange } from 'lib/utils'
import { BreakdownTag } from 'scenes/insights/filters/BreakdownFilter/BreakdownTag'
import MaxTool from 'scenes/max/MaxTool'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { RevenueAnalyticsBreakdown } from '~/queries/schema/schema-general'
import { DateMappingOption } from '~/types'

import { DisplayMode, revenueAnalyticsLogic } from './revenueAnalyticsLogic'

const DATE_FILTER_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Month to date',
        values: ['mStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.startOf('m').format(DATE_FORMAT),
        defaultInterval: 'day',
    },
    {
        key: 'This month',
        values: ['mStart', 'mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('m'), date.endOf('m')),
        defaultInterval: 'day',
    },
    {
        key: 'Last month',
        values: ['-1mStart', '-1mEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'month').startOf('month'), date.subtract(1, 'month').endOf('month')),
        defaultInterval: 'day',
    },
    {
        key: 'This year',
        values: ['yStart', 'yEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date.endOf('y')),
        defaultInterval: 'month',
    },
    {
        key: 'Year to date',
        values: ['yStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => formatDateRange(date.startOf('y'), date.endOf('y')),
        defaultInterval: 'month',
    },
    {
        key: 'Previous year',
        values: ['-1yStart', '-1yEnd'],
        getFormattedDate: (date: dayjs.Dayjs): string =>
            formatDateRange(date.subtract(1, 'year').startOf('y'), date.subtract(1, 'year').endOf('y')),
        defaultInterval: 'month',
    },
    {
        key: 'All time',
        values: ['all'],
        defaultInterval: 'month',
    },
]

// Simple mapping for the display mode options and their icons
const DISPLAY_MODE_OPTIONS: LemonSelectOptions<DisplayMode> = [
    { value: 'line', label: 'Line chart', icon: <IconLineGraph /> },
    { value: 'area', label: 'Area chart', icon: <IconAreaChart /> },
    { value: 'bar', label: 'Bar chart', icon: <IconGraph /> },
]

export const RevenueAnalyticsFilters = (): JSX.Element => {
    const {
        dateFilter: { dateTo, dateFrom },
        insightsDisplayMode,
    } = useValues(revenueAnalyticsLogic)

    const { setDates, setInsightsDisplayMode } = useActions(revenueAnalyticsLogic)

    return (
        <FilterBar
            left={
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={setDates}
                    dateOptions={DATE_FILTER_DATE_OPTIONS}
                    size="small"
                />
            }
            right={
                <>
                    <Tooltip title="Refresh data">
                        <ReloadAll iconOnly />
                    </Tooltip>

                    <LemonSelect
                        value={insightsDisplayMode}
                        onChange={setInsightsDisplayMode}
                        options={DISPLAY_MODE_OPTIONS}
                        size="small"
                    />

                    <RevenueAnalyticsPropertyFilters />
                </>
            }
        />
    )
}

const RevenueAnalyticsPropertyFilters = (): JSX.Element => {
    const {
        revenueAnalyticsFilter,
        breakdownProperties,
        dateFilter: { dateTo, dateFrom },
    } = useValues(revenueAnalyticsLogic)
    const { setRevenueAnalyticsFilters, setDates, setBreakdownProperties } = useActions(revenueAnalyticsLogic)

    const [displayFilters, setDisplayFilters] = useState(false)

    return (
        <MaxTool
            identifier="filter_revenue_analytics"
            context={{
                current_filters: {
                    date_from: dateFrom,
                    date_to: dateTo,
                    breakdown: breakdownProperties,
                    properties: revenueAnalyticsFilter,
                },
            }}
            callback={(toolOutput: Record<string, any>) => {
                // Types suck here, but they *should* be correct if pydantic does its job correctly
                setRevenueAnalyticsFilters(toolOutput.properties)
                setDates(toolOutput.date_from, toolOutput.date_to)
                setBreakdownProperties(toolOutput.breakdown)
            }}
            initialMaxPrompt="Show my revenue for "
            suggestions={[
                'Show my revenue from the last year',
                'Show what my revenue is in France',
                'Break down my revenue by product for the last year',
            ]}
            onMaxOpen={() => setDisplayFilters(false)}
        >
            <div className="flex flex-row gap-2">
                <Popover
                    visible={displayFilters}
                    onClickOutside={() => setDisplayFilters(false)}
                    placement="bottom"
                    className="max-w-200"
                    overlay={
                        <div className="p-2">
                            <PropertyFilters
                                disablePopover
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.RevenueAnalyticsProperties]}
                                onChange={(filters) =>
                                    setRevenueAnalyticsFilters(filters.filter(isRevenueAnalyticsPropertyFilter))
                                }
                                propertyFilters={revenueAnalyticsFilter}
                                pageKey="revenue-analytics"
                                buttonSize="small"
                            />
                        </div>
                    }
                >
                    <LemonButton
                        data-attr="show-revenue-analytics-filters"
                        icon={
                            <IconWithCount count={revenueAnalyticsFilter.length} showZero={false}>
                                <IconFilter />
                            </IconWithCount>
                        }
                        type="secondary"
                        size="small"
                        onClick={() => setDisplayFilters((displayFilters) => !displayFilters)}
                    >
                        Filters
                    </LemonButton>
                </Popover>

                <div className="flex flex-row gap-1">
                    {breakdownProperties.map((breakdown) => (
                        <EditableBreakdownTag key={breakdown.property} breakdown={breakdown} />
                    ))}
                    <AddBreakdownButton />
                </div>
            </div>
        </MaxTool>
    )
}

const AddBreakdownButton = (): JSX.Element => {
    const [open, setOpen] = useState(false)

    const { breakdownProperties } = useValues(revenueAnalyticsLogic)
    const { addBreakdown } = useActions(revenueAnalyticsLogic)

    return (
        <BreakdownPopover open={open} setOpen={setOpen} onSelect={(breakdown) => addBreakdown(breakdown)}>
            <LemonButton
                type="secondary"
                icon={<IconPlusSmall />}
                data-attr="add-breakdown-button"
                onClick={() => setOpen(!open)}
                sideIcon={null}
                disabledReason={breakdownProperties.length >= 2 ? 'You can only have up to 2 breakdowns' : undefined}
                size="small"
            >
                Add breakdown
            </LemonButton>
        </BreakdownPopover>
    )
}

interface EditableBreakdownTagProps {
    breakdown: RevenueAnalyticsBreakdown
}

const EditableBreakdownTag = ({ breakdown }: EditableBreakdownTagProps): JSX.Element => {
    const { removeBreakdown } = useActions(revenueAnalyticsLogic)

    return (
        <BreakdownTag
            breakdown={breakdown.property}
            breakdownType={breakdown.type}
            onClose={() => removeBreakdown(breakdown)}
        />
    )
}

const BreakdownPopover = ({
    open,
    setOpen,
    onSelect,
    children,
}: {
    open: boolean
    setOpen: (open: boolean) => void
    onSelect: (breakdown: RevenueAnalyticsBreakdown) => void
    children?: React.ReactNode
}): JSX.Element => {
    return (
        <Popover
            style={{ minHeight: '200px' }}
            overlay={
                <TaxonomicFilter
                    groupType={TaxonomicFilterGroupType.RevenueAnalyticsProperties}
                    onChange={(_taxonomicGroup, value) => {
                        const breakdown: RevenueAnalyticsBreakdown = {
                            property: value as string,
                            type: 'revenue_analytics',
                        }

                        onSelect(breakdown)
                        setOpen(false)
                    }}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.RevenueAnalyticsProperties]}
                />
            }
            visible={open}
            onClickOutside={() => setOpen(false)}
        >
            {children}
        </Popover>
    )
}
