import { useMemo, useState } from 'react'

import { IconCalendar } from '@posthog/icons'
import { LemonButton, LemonCalendarSelectInput, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { OccurrencesList } from './OccurrencesList'
import {
    buildSummary,
    computePreviewOccurrences,
    DEFAULT_STATE,
    FREQUENCY_OPTIONS,
    getNthWeekdayOfMonth,
    isOneTimeSchedule,
    ONE_TIME_RRULE,
    NTH_LABELS,
    parseRRuleToState,
    stateToRRule,
    WEEKDAY_FULL_LABELS,
    WEEKDAY_LABELS,
    WEEKDAY_PILL_LABELS,
} from './rrule-helpers'
import type { FrequencyOption, MonthlyMode, ScheduleState } from './rrule-helpers'

type ScheduleConfig = {
    rrule: string
    starts_at: string
    timezone?: string
}

interface RecurringSchedulePickerProps {
    schedule?: ScheduleConfig | null
    onChange: (schedule: ScheduleConfig | null) => void
}

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
                        {timezone && timezone !== dayjs.tz.guess() ? ` in ${timezone}` : ''}
                    </div>
                    <div className="space-y-1.5">
                        <OccurrencesList occurrences={previewOccurrences} isFinite={state.endType !== 'never'} />
                    </div>
                </div>
            )}
        </div>
    )
}

export function RecurringSchedulePicker({ schedule, onChange }: RecurringSchedulePickerProps): JSX.Element {
    const isOneTime = schedule ? isOneTimeSchedule(schedule.rrule) : false
    const isRepeating = !!schedule && !isOneTime
    const [state, setState] = useState<ScheduleState>(() =>
        schedule && !isOneTime ? parseRRuleToState(schedule.rrule) : { ...DEFAULT_STATE }
    )

    // Keep start date and timezone in local state so they persist when toggling repeat off
    const [localStartsAt, setLocalStartsAt] = useState<string | null>(schedule?.starts_at || null)
    const [localTimezone, setLocalTimezone] = useState<string>(schedule?.timezone || dayjs.tz.guess())

    const startsAt = schedule?.starts_at || localStartsAt
    const timezone = schedule?.timezone || localTimezone

    const emitChange = (newState: ScheduleState, newStartsAt: string | null, newTimezone: string): void => {
        if (!newStartsAt) {
            return
        }
        const rrule = stateToRRule(newState, newStartsAt)
        onChange({ rrule, starts_at: newStartsAt, timezone: newTimezone })
    }

    const previewOccurrences = useMemo(() => {
        if (!isRepeating || !startsAt) {
            return []
        }
        return computePreviewOccurrences(state, startsAt, timezone)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        isRepeating,
        startsAt,
        timezone,
        state.frequency,
        state.interval,
        state.weekdays,
        state.monthlyMode,
        state.endType,
        state.endDate,
        state.endCount,
    ])

    const summary = isRepeating ? buildSummary(state, startsAt) : null

    const monthlyDayLabel = startsAt ? `Day ${dayjs(startsAt).date()}` : 'Day N'
    const monthlyNthLabel = startsAt
        ? (() => {
              const { n, weekday } = getNthWeekdayOfMonth(dayjs(startsAt))
              return `${NTH_LABELS[n - 1]} ${WEEKDAY_FULL_LABELS[weekday]}`
          })()
        : 'Nth weekday'

    const handleStateChange = (newState: ScheduleState): void => {
        setState(newState)
        emitChange(newState, startsAt, timezone)
    }

    return (
        <div className="flex flex-col gap-3 w-full">
            <div className="flex items-center gap-2">
                <div className="flex-1 min-w-0">
                    <LemonCalendarSelectInput
                        buttonProps={{ fullWidth: true }}
                        clearable
                        value={startsAt ? dayjs(startsAt) : null}
                        onChange={(date) => {
                            const newStartsAt = date ? date.startOf('minute').toISOString() : null
                            const browserTimezone = dayjs.tz.guess()
                            setLocalStartsAt(newStartsAt)
                            setLocalTimezone(browserTimezone)
                            if (newStartsAt) {
                                if (isRepeating) {
                                    emitChange(state, newStartsAt, browserTimezone)
                                } else {
                                    onChange({
                                        rrule: ONE_TIME_RRULE,
                                        starts_at: newStartsAt,
                                        timezone: browserTimezone,
                                    })
                                }
                            } else {
                                onChange(null)
                            }
                        }}
                        granularity="minute"
                        selectionPeriod="upcoming"
                        showTimeToggle={false}
                    />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <span className="text-muted text-sm">Repeat</span>
                    <LemonSwitch
                        checked={isRepeating}
                        onChange={(checked) => {
                            const startDate = localStartsAt || startsAt || new Date().toISOString()
                            setLocalStartsAt(startDate)
                            if (checked) {
                                emitChange(state, startDate, timezone)
                            } else if (startDate) {
                                // Downgrade to one-time schedule
                                onChange({
                                    rrule: ONE_TIME_RRULE,
                                    starts_at: startDate,
                                    timezone,
                                })
                            }
                        }}
                    />
                </div>
            </div>
            {startsAt && (
                <div className="text-xs text-muted -mt-1">
                    Schedule timezone: {timezone} ({dayjs(startsAt).tz(timezone).format('h:mm A')})
                    {timezone !== dayjs.tz.guess() && (
                        <>
                            {' '}
                            · Your time: {dayjs(startsAt).format('h:mm A')} {dayjs.tz.guess()}
                        </>
                    )}
                </div>
            )}

            {isRepeating && (
                <>
                    <div className="flex items-center gap-2 flex-wrap">
                        <FrequencyPicker state={state} onStateChange={handleStateChange} />
                        {state.frequency === 'weekly' && (
                            <WeekdayPicker state={state} onStateChange={handleStateChange} />
                        )}
                        {state.frequency === 'monthly' && (
                            <MonthlyModePicker
                                state={state}
                                onStateChange={handleStateChange}
                                monthlyDayLabel={monthlyDayLabel}
                                monthlyNthLabel={monthlyNthLabel}
                            />
                        )}
                    </div>

                    <EndTypePicker state={state} onStateChange={handleStateChange} />

                    {state.frequency === 'monthly' &&
                        state.monthlyMode === 'day_of_month' &&
                        startsAt &&
                        dayjs(startsAt).date() >= 29 && (
                            <div className="text-xs text-warning">
                                Some months don't have a {dayjs(startsAt).format('Do')}. Those months will be skipped.
                                Use "Last day" to run on the last day of every month instead.
                            </div>
                        )}

                    <SchedulePreview
                        state={state}
                        summary={summary}
                        previewOccurrences={previewOccurrences}
                        timezone={timezone}
                    />
                </>
            )}
        </div>
    )
}
