import { useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    CUSTOM_RANGE,
    DateTimePicker,
    type DateTimeRangeName,
    type DateTimeValue,
    quickRanges,
} from '@posthog/quill-components'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill-primitives'

import { dayjs } from 'lib/dayjs'

// Quick ranges that translate to PostHog relative date strings, so queries stay
// rolling ("-7d" re-resolves on every load). Minute-level ranges are omitted on
// purpose: in PostHog date strings "m" means months, so those apply as absolute
// timestamps instead.
const RANGE_TO_RELATIVE: Partial<Record<DateTimeRangeName, string>> = {
    'Last 1 hour': '-1h',
    'Last 3 hours': '-3h',
    'Last 6 hours': '-6h',
    'Last 12 hours': '-12h',
    'Last 24 hours': '-24h',
    'Last 2 days': '-2d',
    'Last 7 days': '-7d',
    'Last 30 days': '-30d',
    'Last 90 days': '-90d',
    'Last 6 months': '-6m',
    'Last 1 year': '-1y',
    'Last 2 years': '-2y',
}

function toPickerValue(dateFrom: string | null, dateTo: string | null): DateTimeValue {
    const now = new Date()
    if (dateFrom && !dateTo) {
        const name = (Object.keys(RANGE_TO_RELATIVE) as DateTimeRangeName[]).find(
            (key) => RANGE_TO_RELATIVE[key] === dateFrom
        )
        const range = name ? quickRanges.find((r) => r.name === name) : undefined
        if (range) {
            return { start: range.rangeSetter(now), end: now, range }
        }
    }
    return {
        start: dateFrom ? dayjs(dateFrom).toDate() : dayjs(now).subtract(7, 'day').toDate(),
        end: dateTo ? dayjs(dateTo).toDate() : now,
        range: CUSTOM_RANGE,
    }
}

function formatTriggerLabel(value: DateTimeValue): string {
    if (value.range.id !== CUSTOM_RANGE.id) {
        return value.range.name
    }
    return `${dayjs(value.start).format('MMM D, HH:mm')} – ${dayjs(value.end).format('MMM D, HH:mm')}`
}

interface McpDateFilterProps {
    dateFrom: string | null
    dateTo: string | null
    onChange: (dateFrom: string | null, dateTo: string | null) => void
    dataAttr: string
}

export function McpDateFilter({ dateFrom, dateTo, onChange, dataAttr }: McpDateFilterProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const value = toPickerValue(dateFrom, dateTo)

    const handleApply = (next: DateTimeValue): void => {
        const relative = next.range.id !== CUSTOM_RANGE.id ? RANGE_TO_RELATIVE[next.range.name] : undefined
        if (relative) {
            onChange(relative, null)
        } else {
            onChange(next.start.toISOString(), next.end.toISOString())
        }
        setOpen(false)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button variant="outline" data-attr={dataAttr} data-quill>
                        <IconCalendar />
                        {formatTriggerLabel(value)}
                    </Button>
                }
            />
            <PopoverContent align="start" className="w-auto p-0">
                <DateTimePicker value={value} onApply={handleApply} onCancel={() => setOpen(false)} />
            </PopoverContent>
        </Popover>
    )
}
