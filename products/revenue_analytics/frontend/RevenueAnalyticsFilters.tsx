import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { isRevenueAnalyticsPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { DATE_FORMAT, formatDateRange } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'
import { DateMappingOption } from '~/types'

import { revenueAnalyticsLogic } from './revenueAnalyticsLogic'

const DATE_FILTER_DATE_OPTIONS: DateMappingOption[] = [
    { key: CUSTOM_OPTION_KEY, values: [] },
    {
        key: 'Month to date',
        values: ['mStart'],
        getFormattedDate: (date: dayjs.Dayjs): string => date.startOf('d').format(DATE_FORMAT),
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

export const RevenueAnalyticsFilters = (): JSX.Element => {
    const { mobileLayout } = useValues(navigationLogic)
    const {
        revenueAnalyticsFilter,
        dateFilter: { dateTo, dateFrom },
    } = useValues(revenueAnalyticsLogic)

    const { setDates, setRevenueAnalyticsFilters } = useActions(revenueAnalyticsLogic)

    const revenueAnalyticsFiltersEnabled = useFeatureFlag('REVENUE_ANALYTICS_FILTERS')

    return (
        <div
            className={cn(
                'sticky z-20 bg-primary border-b py-2',
                mobileLayout ? 'top-[var(--breadcrumbs-height-full)]' : 'top-[var(--breadcrumbs-height-compact)]'
            )}
        >
            <div className="flex flex-row w-full justify-between gap-1">
                <div className="flex flex-row gap-1">
                    <Tooltip title="Refresh data">
                        <ReloadAll iconOnly />
                    </Tooltip>

                    <DateFilter
                        dateFrom={dateFrom}
                        dateTo={dateTo}
                        onChange={setDates}
                        dateOptions={DATE_FILTER_DATE_OPTIONS}
                    />

                    {revenueAnalyticsFiltersEnabled && (
                        <PropertyFilters
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.RevenueAnalyticsProperties]}
                            onChange={(filters) =>
                                setRevenueAnalyticsFilters(filters.filter(isRevenueAnalyticsPropertyFilter))
                            }
                            propertyFilters={revenueAnalyticsFilter}
                            pageKey="revenue-analytics"
                        />
                    )}
                </div>
            </div>
        </div>
    )
}
