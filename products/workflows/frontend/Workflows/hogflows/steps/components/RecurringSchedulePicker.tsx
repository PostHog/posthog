import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCalendar } from '@posthog/icons'
import {
    LemonButton,
    LemonCalendarSelectInput,
    LemonInput,
    LemonSearchableSelect,
    LemonSelect,
    LemonSwitch,
} from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { timeZoneLabel } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { workflowLogic } from '../../../workflowLogic'
import { OccurrencesList } from './OccurrencesList'
import {
    buildSummary,
    computePreviewOccurrences,
    FREQUENCY_OPTIONS,
    getNthWeekdayOfMonth,
    NTH_LABELS,
    WEEKDAY_FULL_LABELS,
    WEEKDAY_LABELS,
    WEEKDAY_PILL_LABELS,
} from './rrule-helpers'
import type { FrequencyOption, MonthlyMode, ScheduleState } from './rrule-helpers'

interface FrequencyPickerProps {
    state: ScheduleState
    onStateChange: (newState: ScheduleState) => void
}

interface WeekdayPickerProps {
    state: ScheduleState
    onStateChange: (newState: ScheduleState) => void
}

interface MonthlyModePickerProps {
    state: ScheduleState
    onStateChange: (newState: ScheduleState) => void
    monthlyDayLabel: string
    monthlyNthLabel: string
}

interface EndTypePickerProps {
    state: ScheduleState
    onStateChange: (newState: ScheduleState) => void
}

interface SchedulePreviewProps {
    state: ScheduleState
    summary: string | null
    previewOccurrences: Date[]
    timezone?: string
}

function FrequencyPicker({ state, onStateChange }: FrequencyPickerProps): JSX.Element {
    return (
        <>
            <span className="text-muted">Every</span>
            <LemonInput
                type="number"
                min={1}
                max={365}
                size="small"
                value={state.interval}
                onChange={(val) => {
                    onStateChange({ ...state, interval: Math.max(1, Math.min(365, val || 1)) })
                }}
                className="w-14"
            />
            <LemonSelect
                size="small"
                value={state.frequency}
                options={FREQUENCY_OPTIONS}
                onChange={(val) => {
                    onStateChange({ ...state, frequency: val as FrequencyOption })
                }}
            />
            {(state.frequency === 'weekly' || state.frequency === 'monthly') && <span className="text-muted">on</span>}
        </>
    )
}

function WeekdayPicker({ state, onStateChange }: WeekdayPickerProps): JSX.Element {
    return (
        <div className="flex gap-0.5">
            {WEEKDAY_PILL_LABELS.map((label, index) => (
                <LemonButton
                    key={WEEKDAY_LABELS[index]}
                    size="small"
                    type={state.weekdays.includes(index) ? 'primary' : 'secondary'}
                    tooltip={WEEKDAY_FULL_LABELS[index]}
                    onClick={() => {
                        const newWeekdays = state.weekdays.includes(index)
                            ? state.weekdays.filter((d) => d !== index)
                            : [...state.weekdays, index].sort()
                        onStateChange({ ...state, weekdays: newWeekdays })
                    }}
                >
                    {label}
                </LemonButton>
            ))}
        </div>
    )
}

function MonthlyModePicker({
    state,
    onStateChange,
    monthlyDayLabel,
    monthlyNthLabel,
}: MonthlyModePickerProps): JSX.Element {
    return (
        <div className="flex gap-1">
            <LemonButton
                size="small"
                type={state.monthlyMode === 'day_of_month' ? 'primary' : 'secondary'}
                onClick={() => {
                    onStateChange({ ...state, monthlyMode: 'day_of_month' as MonthlyMode })
                }}
            >
                {monthlyDayLabel}
            </LemonButton>
            <LemonButton
                size="small"
                type={state.monthlyMode === 'nth_weekday' ? 'primary' : 'secondary'}
                onClick={() => {
                    onStateChange({ ...state, monthlyMode: 'nth_weekday' as MonthlyMode })
                }}
            >
                {monthlyNthLabel}
            </LemonButton>
            <LemonButton
                size="small"
                type={state.monthlyMode === 'last_day' ? 'primary' : 'secondary'}
                onClick={() => {
                    onStateChange({ ...state, monthlyMode: 'last_day' as MonthlyMode })
                }}
            >
                Last day
            </LemonButton>
        </div>
    )
}

function EndTypePicker({ state, onStateChange }: EndTypePickerProps): JSX.Element {
    return (
        <div className="flex items-center gap-2 flex-wrap">
            <span className="text-muted">Ends</span>
            <div className="flex gap-1">
                {(
                    [
                        { value: 'never', label: 'Never' },
                        { value: 'on_date', label: 'On date' },
                        { value: 'after_count', label: 'After' },
                    ] as const
                ).map((opt) => (
                    <LemonButton
                        key={opt.value}
                        size="small"
                        type={state.endType === opt.value ? 'primary' : 'secondary'}
                        onClick={() => {
                            onStateChange({ ...state, endType: opt.value })
                        }}
                    >
                        {opt.label}
                    </LemonButton>
                ))}
            </div>
            {state.endType === 'after_count' && (
                <>
                    <LemonInput
                        type="number"
                        min={1}
                        max={999}
                        size="small"
                        value={state.endCount}
                        onChange={(val) => {
                            onStateChange({ ...state, endCount: Math.max(1, Math.min(999, val || 1)) })
                        }}
                        className="w-16"
                    />
                    <span className="text-muted text-sm">occurrences</span>
                </>
            )}
            {state.endType === 'on_date' && (
                <div className="shrink-0">
                    <LemonCalendarSelectInput
                        value={state.endDate ? dayjs(state.endDate) : null}
                        onChange={(date) => {
                            onStateChange({ ...state, endDate: date ? date.toISOString() : null })
                        }}
                        granularity="day"
                        selectionPeriod="upcoming"
                        buttonProps={{ size: 'small' }}
                    />
                </div>
            )}
        </div>
    )
}

function SchedulePreview({ state, summary, previewOccurrences, timezone }: SchedulePreviewProps): JSX.Element {
    return (
        <div className="border rounded-lg p-3 bg-bg-light">
            {summary && (
                <div className="flex items-center gap-2 mb-3">
                    <IconCalendar className="text-muted shrink-0" />
                    <span className="text-sm">{summary}</span>
                </div>
            )}

            {previewOccurrences.length > 0 && (
                <div>
                    <div className="text-xs text-muted mb-2">
                        <span className="font-semibold uppercase tracking-wide">
                            {state.endType !== 'never'
                                ? `${previewOccurrences.length} occurrences`
                                : 'Next occurrences'}
                        </span>
                        {timezone ? ` in ${timezone}` : ''}
                    </div>
                    <div className="space-y-1.5">
                        <OccurrencesList occurrences={previewOccurrences} isFinite={state.endType !== 'never'} />
                    </div>
                </div>
            )}
        </div>
    )
}

function TimezoneMenuPicker({ value, onChange }: { value: string; onChange: (timezone: string) => void }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const options = useMemo(
        () =>
            Object.entries(preflight?.available_timezones || {}).map(([tz, offset]) => ({
                value: tz,
                label: timeZoneLabel(tz, offset),
            })),
        [preflight?.available_timezones]
    )

    return (
        <LemonSearchableSelect
            value={value}
            options={options}
            onChange={(val) => val && onChange(val)}
            searchPlaceholder="Search timezones..."
            fullWidth
        />
    )
}

export function RecurringSchedulePicker(): JSX.Element {
    const { scheduleState, scheduleStartsAt, scheduleTimezone, isScheduleRepeating } = useValues(workflowLogic)
    const {
        setScheduleState,
        setScheduleStartsAt,
        setScheduleStartsAtFromPicker,
        setScheduleTimezone,
        setScheduleRepeating,
    } = useActions(workflowLogic)

    const previewOccurrences = useMemo(() => {
        if (!isScheduleRepeating || !scheduleStartsAt) {
            return []
        }
        return computePreviewOccurrences(scheduleState, scheduleStartsAt, scheduleTimezone)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        isScheduleRepeating,
        scheduleStartsAt,
        scheduleTimezone,
        scheduleState.frequency,
        scheduleState.interval,
        scheduleState.weekdays,
        scheduleState.monthlyMode,
        scheduleState.endType,
        scheduleState.endDate,
        scheduleState.endCount,
    ])

    const summary = isScheduleRepeating ? buildSummary(scheduleState, scheduleStartsAt) : null

    const monthlyDayLabel = scheduleStartsAt ? `Day ${dayjs(scheduleStartsAt).date()}` : 'Day N'
    const monthlyNthLabel = scheduleStartsAt
        ? (() => {
              const { n, weekday } = getNthWeekdayOfMonth(dayjs(scheduleStartsAt))
              return `${NTH_LABELS[n - 1]} ${WEEKDAY_FULL_LABELS[weekday]}`
          })()
        : 'Nth weekday'

    return (
        <div className="flex flex-col gap-3 w-full">
            <div className="flex items-center gap-2">
                <div className="flex-1 min-w-0">
                    <LemonCalendarSelectInput
                        buttonProps={{ fullWidth: true }}
                        format="MMMM D, YYYY h:mm A"
                        clearable
                        value={
                            scheduleStartsAt
                                ? dayjs(scheduleStartsAt).tz(scheduleTimezone).tz(dayjs.tz.guess(), true)
                                : null
                        }
                        onChange={(date) => {
                            setScheduleStartsAtFromPicker(date ? date.toISOString() : null)
                        }}
                        granularity="minute"
                        // Recurring schedules use the start date as an anchor for rrule computation,
                        // so past dates are valid. One-time schedules must be in the future.
                        selectionPeriod={isScheduleRepeating ? undefined : 'upcoming'}
                        showTimeToggle={false}
                    />
                </div>
                <div className="w-22 shrink-0">
                    <LemonSwitch
                        label="Repeat"
                        checked={isScheduleRepeating}
                        onChange={(checked) => {
                            if (!scheduleStartsAt) {
                                // If no start date yet, set one so the toggle is meaningful
                                setScheduleStartsAt(new Date().toISOString())
                            }
                            setScheduleRepeating(checked)
                        }}
                    />
                </div>
            </div>
            {scheduleStartsAt && (
                <div className="flex flex-col gap-1 -mt-1">
                    <div className="flex items-center gap-2">
                        <div className="flex-1 min-w-0">
                            <TimezoneMenuPicker
                                value={scheduleTimezone}
                                onChange={(newTimezone) => {
                                    setScheduleTimezone(newTimezone, scheduleTimezone)
                                }}
                            />
                        </div>
                        <div className="w-22 shrink-0" />
                    </div>
                    {scheduleTimezone !== dayjs.tz.guess() && (
                        <span className="text-xs text-muted">
                            Schedule: {dayjs(scheduleStartsAt).tz(scheduleTimezone).format('h:mm A')} {scheduleTimezone}{' '}
                            · Your time: {dayjs(scheduleStartsAt).format('h:mm A')} {dayjs.tz.guess()}
                        </span>
                    )}
                </div>
            )}

            {isScheduleRepeating && (
                <>
                    <div className="flex items-center gap-2 flex-wrap">
                        <FrequencyPicker state={scheduleState} onStateChange={setScheduleState} />
                        {scheduleState.frequency === 'weekly' && (
                            <WeekdayPicker state={scheduleState} onStateChange={setScheduleState} />
                        )}
                        {scheduleState.frequency === 'monthly' && (
                            <MonthlyModePicker
                                state={scheduleState}
                                onStateChange={setScheduleState}
                                monthlyDayLabel={monthlyDayLabel}
                                monthlyNthLabel={monthlyNthLabel}
                            />
                        )}
                    </div>

                    <EndTypePicker state={scheduleState} onStateChange={setScheduleState} />

                    {scheduleState.frequency === 'monthly' &&
                        scheduleState.monthlyMode === 'day_of_month' &&
                        scheduleStartsAt &&
                        dayjs(scheduleStartsAt).date() >= 29 && (
                            <div className="text-xs text-warning">
                                Some months don't have a {dayjs(scheduleStartsAt).format('Do')}. Those months will be
                                skipped. Use "Last day" to run on the last day of every month instead.
                            </div>
                        )}

                    <SchedulePreview
                        state={scheduleState}
                        summary={summary}
                        previewOccurrences={previewOccurrences}
                        timezone={scheduleTimezone}
                    />
                </>
            )}
        </div>
    )
}
