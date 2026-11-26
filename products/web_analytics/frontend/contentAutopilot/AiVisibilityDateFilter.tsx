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
import { CUSTOM_OPTION_KEY, componentsToDayJs, dateFilterToText, dateStringToComponents } from 'lib/utils/dateFilters'
import { formatDate, formatDateRange, isDate } from 'lib/utils/datetime'

import { AI_VISIBILITY_DATE_OPTIONS, type AiVisibilityFilterTab } from './aiVisibilityFilters'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

const DATE_FORMAT = 'YYYY-MM-DD'

interface AiVisibilityRange extends DateTimeRange {
    dateFrom: string
    dateTo: string | null
}

/** A filter value as a local day, so the calendar highlights the days the person picked. */
const toDayjs = (value: string): dayjs.Dayjs => {
    const components = isDate.test(value) ? null : dateStringToComponents(value)
    return components ? componentsToDayJs(components, dayjs().startOf('day')) : dayjs(value)
}

// Ids start at 1 because 0 is CUSTOM_RANGE.
const RANGES: AiVisibilityRange[] = AI_VISIBILITY_DATE_OPTIONS.filter(({ key }) => key !== CUSTOM_OPTION_KEY).map(
    ({ key, values }, index) => ({
        id: index + 1,
        name: key,
        dateFrom: values[0],
        dateTo: values[1] ?? null,
        rangeSetter: () => toDayjs(values[0]).toDate(),
        endSetter: (now) => (values[1] ? toDayjs(values[1]).toDate() : now),
    })
)

const presetFor = (dateFrom: string, dateTo: string | null): AiVisibilityRange | undefined =>
    RANGES.find((range) => range.dateFrom === dateFrom && range.dateTo === dateTo)

const toPickerValue = (dateFrom: string, dateTo: string | null): DateTimeValue => {
    const now = new Date()
    const preset = presetFor(dateFrom, dateTo)
    if (preset) {
        return { start: preset.rangeSetter(now), end: preset.endSetter?.(now) ?? now, range: preset }
    }
    return { start: toDayjs(dateFrom).toDate(), end: dateTo ? toDayjs(dateTo).toDate() : now, range: CUSTOM_RANGE }
}

const triggerLabel = (dateFrom: string, dateTo: string | null): string => {
    const preset = presetFor(dateFrom, dateTo)
    if (preset) {
        return preset.name
    }
    const relative = isDate.test(dateFrom) ? null : dateFilterToText(dateFrom, dateTo, null)
    if (relative) {
        return relative
    }
    const from = toDayjs(dateFrom)
    return dateTo ? formatDateRange(from, toDayjs(dateTo)) : `${formatDate(from)} to now`
}

/** Writes the same values as the Web analytics date filter did, so the date_from and date_to URL params don't change. */
export const AiVisibilityDateFilter = ({ tab }: { tab: AiVisibilityFilterTab }): JSX.Element => {
    const { dateFrom, dateTo } = useValues(contentAutopilotFiltersLogic)
    const { pickDates } = useActions(contentAutopilotFiltersLogic)
    const [open, setOpen] = useState(false)

    const apply = (next: DateTimeValue): void => {
        const preset = RANGES.find((range) => range.id === next.range.id)
        if (preset) {
            pickDates(preset.dateFrom, preset.dateTo, tab)
        } else {
            pickDates(dayjs(next.start).format(DATE_FORMAT), dayjs(next.end).format(DATE_FORMAT), tab)
        }
        setOpen(false)
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button variant="outline" data-attr="date-filter" />}>
                <IconCalendar />
                {triggerLabel(dateFrom, dateTo)}
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
                <DateTimePicker
                    value={toPickerValue(dateFrom, dateTo)}
                    onApply={apply}
                    onCancel={() => setOpen(false)}
                    ranges={RANGES}
                    maxDate={new Date()}
                    showTime={false}
                />
            </PopoverContent>
        </Popover>
    )
}
