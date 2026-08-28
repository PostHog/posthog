import { useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'

import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { QuillDateFilter } from 'lib/components/DateFilter/QuillDateFilter'
import { Button, Popover, PopoverContent, PopoverTrigger, SelectTriggerIcon } from 'lib/ui/quill'
import { dateFilterToText, dateMapping } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'
import { DateMappingOption } from '~/types'

export interface DateRangeButtonProps {
    dateRange: DateRange
    onChange: (dateRange: DateRange) => void
    /** Options the trigger label resolves named ranges against. */
    dateOptions?: DateMappingOption[]
    /** Named preset chips to offer; omit for the picker's own defaults. */
    namedChips?: string[]
    className?: string
    fullWidth?: boolean
}

/** Error tracking's date range control: a quill trigger over the quill date picker. */
export const DateRangeButton = ({
    dateRange,
    onChange,
    dateOptions = dateMapping,
    namedChips,
    className,
    fullWidth = false,
}: DateRangeButtonProps): JSX.Element => {
    const { weekStartDay } = useValues(teamLogic)
    const [open, setOpen] = useState(false)

    const selection = selectionForDateRange(dateRange.date_from ?? '-7d', dateRange.date_to)
    const triggerLabel =
        dateFilterToText(dateRange.date_from, dateRange.date_to, 'Last 7 days', dateOptions, false) ?? 'Last 7 days'

    const applySelection = (nextSelection: Parameters<typeof dateRangeForSelection>[0]): void =>
        onChange({ ...dateRange, ...dateRangeForSelection(nextSelection) })

    return (
        <span className={className}>
            <Popover open={open} onOpenChange={setOpen}>
                <PopoverTrigger
                    render={
                        <Button
                            variant="outline"
                            size="default"
                            className={fullWidth ? 'w-full' : undefined}
                            data-attr="date-filter"
                        />
                    }
                >
                    <IconCalendar />
                    <span className="text-nowrap">{triggerLabel}</span>
                    <SelectTriggerIcon />
                </PopoverTrigger>
                <PopoverContent
                    align="start"
                    collisionAvoidance={{ side: 'flip', align: 'shift', fallbackAxisSide: 'none' }}
                    className="w-auto overflow-hidden border-none p-0 shadow-none ring-0"
                >
                    <QuillDateFilter
                        selection={selection}
                        onSelectionChange={(nextSelection) => {
                            applySelection(nextSelection)
                            // Rolling steppers keep the panel open so the count can be nudged.
                            if (nextSelection.kind !== 'rolling') {
                                setOpen(false)
                            }
                        }}
                        onApplyCustom={(nextSelection) => {
                            applySelection(nextSelection)
                            setOpen(false)
                        }}
                        namedChips={namedChips}
                        weekStartsOn={weekStartDay === 1 ? 1 : 0}
                    />
                </PopoverContent>
            </Popover>
        </span>
    )
}
