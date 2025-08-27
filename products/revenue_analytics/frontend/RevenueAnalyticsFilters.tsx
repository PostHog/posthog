import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconFilter, IconGraph, IconLineGraph } from '@posthog/icons'
import {
    LemonButton,
    LemonInputSelect,
    LemonInputSelectOption,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    Popover,
    Tooltip,
} from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { FilterBar } from 'lib/components/FilterBar'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isRevenueAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { IconAreaChart, IconWithCount } from 'lib/lemon-ui/icons'
import { DATE_FORMAT, formatDateRange } from 'lib/utils'

import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { RevenueAnalyticsGroupBy } from '~/queries/schema/schema-general'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
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
const DISPLAY_MODE_OPTIONS: LemonSegmentedButtonOption<DisplayMode>[] = [
    { value: 'line', icon: <IconLineGraph /> },
    { value: 'area', icon: <IconAreaChart /> },
    { value: 'bar', icon: <IconGraph /> },
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
                <Tooltip title="Refresh data">
                    <ReloadAll iconOnly />
                </Tooltip>
            }
            right={
                <>
                    <LemonSegmentedButton
                        value={insightsDisplayMode}
                        onChange={setInsightsDisplayMode}
                        options={DISPLAY_MODE_OPTIONS}
                    />

                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                        dateOptions={DATE_FILTER_DATE_OPTIONS}
                    />

                    <RevenueAnalyticsPropertyFilters />
                    <RevenueAnalyticsBreakdownBy />
                </>
            }
        />
    )
}

const RevenueAnalyticsPropertyFilters = (): JSX.Element => {
    const { revenueAnalyticsFilter } = useValues(revenueAnalyticsLogic)
    const { setRevenueAnalyticsFilters } = useActions(revenueAnalyticsLogic)

    const [displayFilters, setDisplayFilters] = useState(false)

    return (
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
                    />
                </div>
            }
        >
            <LemonButton
                icon={
                    <IconWithCount count={revenueAnalyticsFilter.length} showZero={false}>
                        <IconFilter />
                    </IconWithCount>
                }
                type="secondary"
                data-attr="show-revenue-analytics-filters"
                onClick={() => setDisplayFilters((displayFilters) => !displayFilters)}
            >
                Filters
            </LemonButton>
        </Popover>
    )
}

// We're defining the options here as a Record to get type-safety guarantee we'll
// include all the options.
const BREAKDOWN_BY_MAPPING: Record<RevenueAnalyticsGroupBy, string> = {
    [RevenueAnalyticsGroupBy.COHORT]: 'Cohort',
    [RevenueAnalyticsGroupBy.COUNTRY]: 'Country',
    [RevenueAnalyticsGroupBy.COUPON]: 'Coupon',
    [RevenueAnalyticsGroupBy.COUPON_ID]: 'Coupon ID',
    [RevenueAnalyticsGroupBy.INITIAL_COUPON]: 'Initial coupon',
    [RevenueAnalyticsGroupBy.INITIAL_COUPON_ID]: 'Initial coupon ID',
    [RevenueAnalyticsGroupBy.PRODUCT]: 'Product',
}

const BREAKDOWN_BY_OPTIONS: LemonInputSelectOption[] = Object.entries(BREAKDOWN_BY_MAPPING).map(([key, label]) => ({
    key,
    label,
    tooltip: CORE_FILTER_DEFINITIONS_BY_GROUP['revenue_analytics_properties'][key]?.description,
}))

const RevenueAnalyticsBreakdownBy = (): JSX.Element => {
    const { groupBy } = useValues(revenueAnalyticsLogic)
    const { setGroupBy } = useActions(revenueAnalyticsLogic)

    return (
        <div className="flex items-center gap-1 text-muted-alt">
            <span>{groupBy.length > 0 && 'Breakdown by'}</span>
            <LemonInputSelect
                options={BREAKDOWN_BY_OPTIONS}
                value={groupBy}
                onChange={(value) => setGroupBy(value as RevenueAnalyticsGroupBy[])}
                mode="multiple"
                disablePrompting
                limit={2}
                placeholder="Breakdown by"
            />
        </div>
    )
}
