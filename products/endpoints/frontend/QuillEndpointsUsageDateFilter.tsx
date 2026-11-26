import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    Button,
    CUSTOM_RANGE,
    DateTimePicker,
    type DateTimeRange,
    type DateTimeValue,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { ENDPOINTS_USAGE_DATE_RANGES } from './endpointsUsageDateRanges'
import { endpointsUsageLogic } from './endpointsUsageLogic'

const DATE_FORMAT = 'YYYY-MM-DD'

interface UsageRange extends DateTimeRange {
    key: string
}

// Ids start at 1 because 0 is CUSTOM_RANGE.
const USAGE_RANGES: UsageRange[] = ENDPOINTS_USAGE_DATE_RANGES.map((range, index) => ({
    id: index + 1,
    name: range.label,
    key: range.key,
    rangeSetter: (now) => range.start(dayjs(now)).toDate(),
}))

function toPickerValue(dateFrom: string | null, dateTo: string | null): DateTimeValue {
    const now = new Date()
    const preset = dateTo === null ? USAGE_RANGES.find((range) => range.key === dateFrom) : undefined
    if (preset) {
        return { start: preset.rangeSetter(now), end: now, range: preset }
    }
    return {
        start: (dateStringToDayJs(dateFrom) ?? dayjs(now).subtract(7, 'day')).toDate(),
        end: (dateTo ? dateStringToDayJs(dateTo) : null)?.toDate() ?? now,
        range: CUSTOM_RANGE,
    }
}

function triggerLabel(value: DateTimeValue): string {
    if (value.range.id !== CUSTOM_RANGE.id) {
        return value.range.name
    }
    return `${dayjs(value.start).format('MMM D, YYYY')} to ${dayjs(value.end).format('MMM D, YYYY')}`
}

export function QuillEndpointsUsageDateFilter(): JSX.Element {
    const { dateFilter } = useValues(endpointsUsageLogic)
    const { setDates } = useActions(endpointsUsageLogic)
    const [open, setOpen] = useState(false)
    const value = toPickerValue(dateFilter.dateFrom, dateFilter.dateTo)

    const apply = (next: DateTimeValue): void => {
        const preset = USAGE_RANGES.find((range) => range.id === next.range.id)
        if (preset) {
            setDates(preset.key, null)
        } else {
            setDates(dayjs(next.start).format(DATE_FORMAT), dayjs(next.end).format(DATE_FORMAT))
        }
        setOpen(false)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button variant="outline" data-attr="endpoints-usage-date-range" />}>
                <IconCalendar />
                {triggerLabel(value)}
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
                <DateTimePicker
                    value={value}
                    onApply={apply}
                    onCancel={() => setOpen(false)}
                    ranges={USAGE_RANGES}
                    maxDate={new Date()}
                    showTime={false}
                />
            </PopoverContent>
        </Popover>
    )
}
