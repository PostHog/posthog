import { useState } from 'react'

import { IconCalendar, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonDivider, Popover } from '@posthog/lemon-ui'

import 'lib/components/DateFilter/DateRangePicker/DateRangePicker.scss'
import { dayjs } from 'lib/dayjs'
import { LemonCalendar, LemonCalendarDateState } from 'lib/lemon-ui/LemonCalendar/LemonCalendar'

import type { DateRange } from '~/queries/schema/schema-general'

import {
    ANOMALIES_ROLLING_OPTIONS,
    MAX_WINDOW_START_AGE_DAYS,
    WEEK_DAYS,
    isWindowStartAllowed,
    resolveAnomaliesWindow,
    stepAnomaliesWindow,
    weekStartingOn,
} from 'products/logs/frontend/anomaliesDateWindow'

export interface AnomaliesDatePickerProps {
    dateRange: DateRange
    setDateRange: (dateRange: DateRange) => void
    stepDateRange: (direction: -1 | 1) => void
}

export function AnomaliesDatePicker({ dateRange, setDateRange, stepDateRange }: AnomaliesDatePickerProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const now = dayjs()
    const resolved = resolveAnomaliesWindow(dateRange, now)
    const rollingOption = ANOMALIES_ROLLING_OPTIONS.find(
        (option) => option.dateFrom === dateRange.date_from && !dateRange.date_to
    )
    const weekStart = resolved && !resolved.rolling ? resolved.start.startOf('day') : null

    const label = rollingOption
        ? `Last ${rollingOption.label}`
        : resolved
          ? `${resolved.start.format('MMM D, HH:mm')} - ${resolved.rolling ? 'now' : resolved.end.format('MMM D, HH:mm')}`
          : 'Pick a week'

    const getDateState = ({ date }: { date: dayjs.Dayjs }): LemonCalendarDateState => {
        if (!isWindowStartAllowed(date.startOf('day'), now)) {
            return {
                disabledReason: date.isAfter(now)
                    ? 'This day is in the future'
                    : `Log volume older than ${MAX_WINDOW_START_AGE_DAYS} days has expired`,
            }
        }
        if (!weekStart) {
            return {}
        }
        const offset = date.startOf('day').diff(weekStart, 'day')
        return {
            isStart: offset === 0,
            isBetween: offset > 0 && offset < WEEK_DAYS - 1,
            isEnd: offset === WEEK_DAYS - 1,
        }
    }

    const select = (next: DateRange): void => {
        setDateRange(next)
        setOpen(false)
    }

    return (
        <div className="DateRangePickerButtonGroup">
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconChevronLeft />}
                tooltip="Previous window"
                disabledReason={
                    stepAnomaliesWindow(dateRange, -1, now)
                        ? undefined
                        : `Log volume older than ${MAX_WINDOW_START_AGE_DAYS} days has expired`
                }
                onClick={() => stepDateRange(-1)}
                data-attr="logs-anomalies-date-previous"
            />
            <Popover
                visible={open}
                onClickOutside={() => setOpen(false)}
                placement="bottom-start"
                overlay={
                    <div className="flex">
                        <div className="flex flex-col gap-1 p-2">
                            <div className="text-xs font-medium text-secondary px-1">Week starting</div>
                            <LemonCalendar
                                leftmostMonth={(weekStart ?? now).startOf('month')}
                                onDateClick={(date) => select(weekStartingOn(date))}
                                getDateState={getDateState}
                            />
                        </div>
                        <LemonDivider vertical className="my-3" />
                        <div className="flex flex-col gap-1 p-3">
                            <div className="text-xs font-medium text-secondary mb-1">In the last</div>
                            {ANOMALIES_ROLLING_OPTIONS.map((option) => (
                                <LemonButton
                                    key={option.dateFrom}
                                    size="small"
                                    type={option === rollingOption ? 'primary' : 'tertiary'}
                                    fullWidth
                                    onClick={() => select({ date_from: option.dateFrom, date_to: null })}
                                >
                                    {option.label}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                }
            >
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconCalendar />}
                    onClick={() => setOpen(!open)}
                    data-attr="logs-anomalies-date-picker"
                >
                    {label}
                </LemonButton>
            </Popover>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconChevronRight />}
                tooltip="Next window"
                disabledReason={resolved?.rolling ? 'This window already ends now' : undefined}
                onClick={() => stepDateRange(1)}
                data-attr="logs-anomalies-date-next"
            />
        </div>
    )
}
