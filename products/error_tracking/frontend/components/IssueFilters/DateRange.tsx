import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar, IconChevronDown } from '@posthog/icons'

import { selectionForDateRange, dateRangeForSelection } from 'lib/components/DateFilter/dateRangeSelection'
import { QuillDateFilter } from 'lib/components/DateFilter/QuillDateFilter'
import { Button, Popover, PopoverContent, PopoverTrigger } from 'lib/ui/quill'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { issueFiltersLogic } from './issueFiltersLogic'

const ERROR_TRACKING_NAMED_CHIPS = ['Last week', 'Last month', 'This week', 'This month', 'This year']
const ERROR_TRACKING_DATE_OPTIONS = dateMapping.filter(
    (option) => !['Yesterday', 'All time', 'Today'].includes(option.key)
)
const LEMON_SKIN_PROPS = { 'data-lemon-skin': 'true' } as const

export const DateRangeFilter = ({
    className,
    fullWidth = false,
}: {
    className?: string
    fullWidth?: boolean
}): JSX.Element => {
    const { dateRange } = useValues(issueFiltersLogic)
    const { setDateRange } = useActions(issueFiltersLogic)
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const selection = selectionForDateRange(dateRange.date_from ?? '-7d', dateRange.date_to)
    const triggerLabel =
        dateFilterToText(dateRange.date_from, dateRange.date_to, 'Last 7 days', ERROR_TRACKING_DATE_OPTIONS, false) ??
        'Last 7 days'

    return (
        <span className={className}>
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            className={fullWidth ? 'w-full' : undefined}
                            data-quill
                            data-lemon-skin
                            data-attr="date-filter"
                        />
                    }
                >
                    <IconCalendar />
                    <span className="text-nowrap">{triggerLabel}</span>
                    <IconChevronDown />
                </PopoverTrigger>
                <PopoverContent
                    align="start"
                    collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                    className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                    {...LEMON_SKIN_PROPS}
                >
                    <QuillDateFilter
                        selection={selection}
                        onSelectionChange={(nextSelection) => {
                            setDateRange({ ...dateRange, ...dateRangeForSelection(nextSelection) })
                            if (nextSelection.kind !== 'rolling') {
                                setOpen(false)
                            }
                        }}
                        onApplyCustom={(nextSelection) => {
                            setDateRange({ ...dateRange, ...dateRangeForSelection(nextSelection) })
                            setOpen(false)
                        }}
                        namedChips={ERROR_TRACKING_NAMED_CHIPS}
                        weekStartsOn={weekStartDay === 1 ? 1 : 0}
                        portalProps={LEMON_SKIN_PROPS}
                    />
                </PopoverContent>
            </Popover>
        </span>
    )
}
