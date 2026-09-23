import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCalendar, IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonDivider, Popover } from '@posthog/lemon-ui'

import 'lib/components/DateFilter/DateRangePicker/DateRangePicker.scss'
import { dayjs } from 'lib/dayjs'
import { LemonCalendar, LemonCalendarDateState } from 'lib/lemon-ui/LemonCalendar/LemonCalendar'

import type { DateRange } from '~/queries/schema/schema-general'

import {
    ANOMALIES_ROLLING_OPTIONS,
    MAX_WINDOW_START_AGE_DAYS,
    anomaliesWindowDays,
    oldestAllowedStart,
    resolveAnomaliesWindow,
    stepAnomaliesWindow,
    weekStartingOn,
} from 'products/logs/frontend/anomaliesDateWindow'
import { logsAnomaliesLogic } from 'products/logs/frontend/logsAnomaliesLogic'

// The rollup keeps volume for longer than this. The limit is on where a window may start, so the
// message states that rule rather than claiming the older data is gone.
const WINDOW_START_LIMIT_REASON = `A window can start at most ${MAX_WINDOW_START_AGE_DAYS} days ago`

function formatLabel(dateRange: DateRange, now: dayjs.Dayjs): string {
    const rolling = ANOMALIES_ROLLING_OPTIONS.find((option) => option.dateFrom === dateRange.date_from)
    if (rolling && !dateRange.date_to) {
        return `Last ${rolling.label}`
    }
    const window = resolveAnomaliesWindow(dateRange, now)
    if (!window) {
        return 'Pick a week'
    }
    const end = dateRange.date_to ? window.end.format('MMM D, HH:mm') : 'now'
    return `${window.start.format('MMM D, HH:mm')} - ${end}`
}

export function AnomaliesDatePicker(): JSX.Element {
    const { dateRange, seriesBandsLoading } = useValues(logsAnomaliesLogic)
    const { setDateRange, stepDateRange } = useActions(logsAnomaliesLogic)
    const [open, setOpen] = useState(false)
    const now = dayjs()
    const oldest = oldestAllowedStart(now)
    const canStepBack = !!stepAnomaliesWindow(dateRange, -1, now)
    const canStepForward = !!stepAnomaliesWindow(dateRange, 1, now)
    // Every control here starts a band query, and the backend runs it synchronously. Without this a
    // run of quick clicks starts a query per click, and only the last answer is wanted.
    const loadingReason = seriesBandsLoading ? 'The chart is still loading' : undefined

    const bandDays = anomaliesWindowDays(dateRange, now)
    const bandFirstMs = bandDays?.firstMs
    // LemonCalendar resets its month whenever this prop changes identity, so it must not change on every render.
    const leftmostMonth = useMemo(() => dayjs(bandFirstMs).startOf('month'), [bandFirstMs])

    const getDateState = ({ date }: { date: dayjs.Dayjs }): LemonCalendarDateState => {
        const day = date.startOf('day')
        if (day.isAfter(now)) {
            return { disabledReason: 'This day is in the future' }
        }
        if (day.isBefore(oldest)) {
            return { disabledReason: WINDOW_START_LIMIT_REASON }
        }
        if (!bandDays) {
            return { disabledReason: loadingReason }
        }
        const dayMs = day.valueOf()
        return {
            disabledReason: loadingReason,
            isStart: dayMs === bandDays.firstMs,
            isBetween: dayMs > bandDays.firstMs && dayMs < bandDays.lastMs,
            isEnd: dayMs === bandDays.lastMs,
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
                disabledReason={canStepBack ? loadingReason : WINDOW_START_LIMIT_REASON}
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
                                leftmostMonth={leftmostMonth}
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
                                    type={
                                        option.dateFrom === dateRange.date_from && !dateRange.date_to
                                            ? 'primary'
                                            : 'tertiary'
                                    }
                                    fullWidth
                                    disabledReason={loadingReason}
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
                    {formatLabel(dateRange, now)}
                </LemonButton>
            </Popover>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconChevronRight />}
                tooltip="Next window"
                disabledReason={canStepForward ? loadingReason : 'This window already ends now'}
                onClick={() => stepDateRange(1)}
                data-attr="logs-anomalies-date-next"
            />
        </div>
    )
}
