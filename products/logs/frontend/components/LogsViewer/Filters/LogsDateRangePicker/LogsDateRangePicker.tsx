import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCalendar, IconClock } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Popover } from '@posthog/lemon-ui'

import { RollingDateRangeFilter } from 'lib/components/DateFilter/RollingDateRangeFilter'
import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { DateRange } from '~/queries/schema/schema-general'
import { DateMappingOption } from '~/types'

import { TimezoneSelect } from 'products/logs/frontend/components/LogsViewer/TimezoneSelect'
import { logsViewerSettingsLogic } from 'products/logs/frontend/components/LogsViewer/logsViewerSettingsLogic'

import { LOGS_DATE_OPTIONS } from './constants'
import { logsDateRangePickerLogic } from './logsDateRangePickerLogic'
import { DATE_TIME_FORMAT, formatDateRangeLabel, getShortLabel, parseDateExpression } from './utils'

interface DateTimeInputProps {
    value: string
    onChange: (value: string) => void
    placeholder: string
    timezone: string
    label: string
}

const DateTimeInput = ({ value, onChange, placeholder, timezone, label }: DateTimeInputProps): JSX.Element => {
    const [calendarOpen, setCalendarOpen] = useState(false)

    const parsedValue = parseDateExpression(value, timezone)

    const handleCalendarSelect = (date: dayjs.Dayjs): void => {
        onChange(date.format(DATE_TIME_FORMAT))
        setCalendarOpen(false)
    }

    return (
        <div className="flex-1">
            <div className="text-xs text-secondary mb-1">{label}</div>
            <Popover
                visible={calendarOpen}
                onClickOutside={() => setCalendarOpen(false)}
                placement="bottom-start"
                overlay={
                    <LemonCalendarSelect
                        value={parsedValue}
                        onChange={handleCalendarSelect}
                        onClose={() => setCalendarOpen(false)}
                        granularity="minute"
                        use24HourFormat
                    />
                }
            >
                <LemonInput
                    value={value}
                    onChange={onChange}
                    placeholder={placeholder}
                    suffix={
                        <LemonButton
                            size="xsmall"
                            noPadding
                            icon={<IconCalendar className="text-secondary" />}
                            onClick={(e) => {
                                e.stopPropagation()
                                setCalendarOpen(true)
                            }}
                        />
                    }
                />
            </Popover>
        </div>
    )
}

export interface LogsDateRangePickerProps {
    dateRange: DateRange
    setDateRange: (dateRange: DateRange) => void
}

export const LogsDateRangePicker = ({ dateRange, setDateRange }: LogsDateRangePickerProps): JSX.Element => {
    const { popoverOpen, customFrom, customTo, history } = useValues(logsDateRangePickerLogic)
    const { setPopoverOpen, setCustomFrom, setCustomTo, addToHistory } = useActions(logsDateRangePickerLogic)
    const { timezone } = useValues(logsViewerSettingsLogic)
    const { setTimezone } = useActions(logsViewerSettingsLogic)

    const handleSelectOption = (option: DateMappingOption): void => {
        setDateRange({ date_from: option.values[0], date_to: option.values[1] ?? null })
        addToHistory({ date_from: option.values[0], date_to: option.values[1] ?? null })
        setPopoverOpen(false)
    }

    const handleSelectHistory = (historyDateRange: DateRange): void => {
        setDateRange(historyDateRange)
        addToHistory(historyDateRange)
        setPopoverOpen(false)
    }

    const handleApplyCustom = (): void => {
        const fromDate = parseDateExpression(customFrom, timezone)
        const toDate = customTo ? parseDateExpression(customTo, timezone) : null

        if (!fromDate) {
            lemonToast.error('Invalid start date format. Use formats like "-1h", "-30M", or "YYYY-MM-DD HH:mm"')
            return
        }

        if (customTo && !toDate) {
            lemonToast.error('Invalid end date format. Use formats like "-1h", "-30M", or "YYYY-MM-DD HH:mm"')
            return
        }

        if (toDate && fromDate.isAfter(toDate)) {
            lemonToast.error('Start date must be before end date')
            return
        }

        const newDateRange: DateRange = {
            date_from: fromDate.toISOString(),
            date_to: toDate ? toDate.toISOString() : null,
        }

        setDateRange(newDateRange)
        addToHistory(newDateRange)
        setPopoverOpen(false)
    }

    const isOptionSelected = (option: DateMappingOption): boolean => {
        return dateRange.date_from === option.values[0] && (dateRange.date_to ?? null) === (option.values[1] ?? null)
    }

    const currentLabel = formatDateRangeLabel(dateRange, timezone, LOGS_DATE_OPTIONS)

    return (
        <Popover
            visible={popoverOpen}
            onClickOutside={() => setPopoverOpen(false)}
            placement="bottom-end"
            overlay={
                <div className="w-fit bg-bg-light rounded-lg overflow-hidden flex flex-row-reverse">
                    <div className="flex flex-col gap-1 p-3">
                        <div className="text-xs font-medium text-secondary mb-1">In the last</div>
                        {LOGS_DATE_OPTIONS.map((option) => (
                            <LemonButton
                                key={option.key}
                                size="small"
                                type={isOptionSelected(option) ? 'primary' : 'tertiary'}
                                onClick={() => handleSelectOption(option)}
                                fullWidth
                            >
                                {getShortLabel(option)}
                            </LemonButton>
                        ))}
                        <RollingDateRangeFilter
                            dateFrom={dateRange.date_from}
                            selected={true}
                            dateRangeFilterLabel=""
                            onChange={(fromDate) => {
                                setDateRange({ date_from: fromDate, date_to: null })
                                addToHistory({ date_from: fromDate, date_to: null })
                            }}
                            fullWidth
                            allowedDateOptions={['minutes', 'hours', 'days']}
                        />
                    </div>

                    <LemonDivider vertical className="my-3" />

                    <div className="flex flex-col gap-3 p-3 w-fit">
                        <div className="flex flex-col gap-2">
                            <div className="text-xs font-medium text-secondary">Custom range</div>
                            <div className="flex gap-2">
                                <DateTimeInput
                                    value={customFrom}
                                    onChange={setCustomFrom}
                                    placeholder="-1h, -30M..."
                                    timezone={timezone}
                                    label="From"
                                />
                                <DateTimeInput
                                    value={customTo}
                                    onChange={setCustomTo}
                                    placeholder="now"
                                    timezone={timezone}
                                    label="To"
                                />
                            </div>
                            <LemonButton type="primary" size="small" onClick={handleApplyCustom} fullWidth>
                                Apply
                            </LemonButton>
                        </div>

                        {history.length > 0 && (
                            <>
                                <LemonDivider className="my-0" />
                                <div className="flex flex-col gap-1 flex-1">
                                    <div className="text-xs font-medium text-secondary">Recent</div>
                                    {history.map((historyDateRange, index) => (
                                        <LemonButton
                                            key={index}
                                            size="small"
                                            type="tertiary"
                                            fullWidth
                                            icon={<IconClock className="text-secondary" />}
                                            onClick={() => handleSelectHistory(historyDateRange)}
                                        >
                                            <span className="truncate">
                                                {formatDateRangeLabel(historyDateRange, timezone, LOGS_DATE_OPTIONS)}
                                            </span>
                                        </LemonButton>
                                    ))}
                                </div>
                            </>
                        )}

                        <LemonDivider className="my-0" />
                        <TimezoneSelect value={timezone} onChange={setTimezone} size="xsmall" />
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconCalendar />}
                onClick={() => setPopoverOpen(!popoverOpen)}
            >
                {currentLabel}
            </LemonButton>
        </Popover>
    )
}
