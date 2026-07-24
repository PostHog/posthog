import { useActions, useValues } from 'kea'

import { IconCalendar, IconChevronDown } from '@posthog/icons'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Button } from 'lib/ui/quill'
import { dateMapping } from 'lib/utils/dateFilters'

import { issueFiltersLogic } from './issueFiltersLogic'

const errorTrackingDateOptions = dateMapping.filter((dm) => !['Yesterday', 'All time', 'Today'].includes(dm.key))

export const DateRangeFilter = ({
    className,
    fullWidth = false,
    size = 'small',
}: {
    className?: string
    fullWidth?: boolean
    size?: 'xsmall' | 'small' | 'medium' | 'large'
}): JSX.Element => {
    const { dateRange } = useValues(issueFiltersLogic)
    const { setDateRange } = useActions(issueFiltersLogic)
    return (
        <span className={className}>
            <DateFilter
                size={size}
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
                fullWidth={fullWidth}
                dateOptions={errorTrackingDateOptions}
                onChange={(changedDateFrom, changedDateTo) =>
                    setDateRange({ date_from: changedDateFrom, date_to: changedDateTo })
                }
                allowedRollingDateOptions={['hours', 'days', 'weeks', 'months', 'years']}
                renderTrigger={({ buttonRef, disabledReason, fullWidth, isOpen, label, onClick, title }) => (
                    <Button
                        ref={buttonRef}
                        variant="outline"
                        size="default"
                        className={fullWidth ? 'w-full' : undefined}
                        disabled={!!disabledReason}
                        aria-expanded={isOpen}
                        data-attr="date-filter"
                        onClick={onClick}
                        title={disabledReason ?? title}
                    >
                        <IconCalendar />
                        <span className="text-nowrap">{label}</span>
                        <IconChevronDown className="size-4" />
                    </Button>
                )}
            />
        </span>
    )
}
