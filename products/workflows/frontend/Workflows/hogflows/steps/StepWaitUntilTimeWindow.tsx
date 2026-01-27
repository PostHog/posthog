import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonDivider, LemonInputSelect, LemonLabel, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { timeZoneLabel } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import { WeekdayType } from '~/types'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import { stepWaitUntilTimeWindowLogic } from './stepWaitUntilTimeWindowLogic'

type DayConfig = 'any' | 'weekday' | 'weekend' | WeekdayType[]
type TimeConfig = 'any' | [string, string]

type WaitUntilTimeWindowAction = Extract<HogFlowAction, { type: 'wait_until_time_window' }>

const DEFAULT_TIME_RANGE: [string, string] = ['09:00', '17:00']
const DEFAULT_WEEKDAYS: WeekdayType[] = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']

const DATE_OPTIONS = [
    { value: 'any', label: 'Any day' },
    { value: 'weekday', label: 'Weekdays' },
    { value: 'weekend', label: 'Weekends' },
    { value: 'custom', label: 'Specific days' },
]

const TIME_OPTIONS = [
    { value: 'any', label: 'Any time' },
    { value: 'custom', label: 'Specific time range' },
]

const WEEKDAY_OPTIONS = [
    { key: 'monday', label: 'Monday' },
    { key: 'tuesday', label: 'Tuesday' },
    { key: 'wednesday', label: 'Wednesday' },
    { key: 'thursday', label: 'Thursday' },
    { key: 'friday', label: 'Friday' },
    { key: 'saturday', label: 'Saturday' },
    { key: 'sunday', label: 'Sunday' },
]

// Generate time range options (00:00 to 23:00)
const TIME_RANGE_OPTIONS = Array.from({ length: 24 }, (_, i) => ({
    value: `${i.toString().padStart(2, '0')}:00`,
    label: `${i.toString().padStart(2, '0')}:00`,
}))

// Configuration utility functions
const isCustomDay = (day: DayConfig): day is WeekdayType[] => {
    return Array.isArray(day)
}

const isCustomTime = (time: TimeConfig): time is [string, string] => {
    return Array.isArray(time)
}

const getDaySelectValue = (day: DayConfig): string => {
    if (day === 'any' || day === 'weekday' || day === 'weekend') {
        return day
    }
    return 'custom'
}

const convertStringToDayConfig = (value: string): DayConfig => {
    switch (value) {
        case 'any':
        case 'weekday':
        case 'weekend':
            return value
        case 'custom':
            return DEFAULT_WEEKDAYS
        default:
            return 'any'
    }
}

const getUpdatedDayConfig = (value: string): { day: DayConfig } => {
    const newDayValue = convertStringToDayConfig(value)
    return { day: newDayValue }
}

const getUpdatedTimeConfig = (value: string): { time: TimeConfig } => {
    if (value === 'custom') {
        return { time: DEFAULT_TIME_RANGE }
    }
    return { time: value as 'any' }
}

const getUpdatedTimeRangeConfig = (
    newTime: string,
    index: 0 | 1,
    currentTime: [string, string]
): { time: [string, string] } => {
    const updatedTime: [string, string] = [...currentTime]
    updatedTime[index] = newTime
    return { time: updatedTime }
}

export function StepWaitUntilTimeWindowConfiguration({ node }: { node: Node<WaitUntilTimeWindowAction> }): JSX.Element {
    const action = node.data
    const { timezone, day, time, use_person_timezone, fallback_timezone } = action.config

    const { logicProps } = useValues(workflowLogic)
    const { partialSetWaitUntilTimeWindowConfig } = useActions(
        stepWaitUntilTimeWindowLogic({ workflowLogicProps: logicProps })
    )
    const { preflight } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const showPersonTimezone = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_PERSON_TIMEZONE]

    const timezoneOptions = Object.entries(preflight?.available_timezones || {}).map(([tz, offset]) => ({
        key: tz,
        label: timeZoneLabel(tz, offset),
    }))

    const isCustomDate = isCustomDay(day)
    const isCustomTimeRange = isCustomTime(time)

    const handleTimezoneChange = (newTimezone: string[]): void => {
        if (!preflight?.available_timezones) {
            throw new Error('No timezones are available')
        }
        partialSetWaitUntilTimeWindowConfig(action.id, { timezone: newTimezone[0] })
    }

    const handleUsePersonTimezoneChange = (checked: boolean): void => {
        partialSetWaitUntilTimeWindowConfig(action.id, { use_person_timezone: checked })
    }

    const handleFallbackTimezoneChange = (newTimezone: string[]): void => {
        if (!preflight?.available_timezones) {
            throw new Error('No timezones are available')
        }
        partialSetWaitUntilTimeWindowConfig(action.id, { fallback_timezone: newTimezone[0] })
    }

    return (
        <>
            <StepSchemaErrors />
            <div className="flex flex-col gap-4">
                <div className="flex flex-wrap">
                    <DayConfiguration
                        day={day}
                        isCustomDate={isCustomDate}
                        onDayChange={(value) => {
                            const config = getUpdatedDayConfig(value)
                            partialSetWaitUntilTimeWindowConfig(action.id, config)
                        }}
                        onCustomDaysChange={(newDays) =>
                            partialSetWaitUntilTimeWindowConfig(action.id, { day: [...newDays] as WeekdayType[] })
                        }
                    />

                    <LemonDivider vertical />

                    <TimeConfiguration
                        time={time}
                        isCustomTime={isCustomTimeRange}
                        onTimeChange={(value) => {
                            const config = getUpdatedTimeConfig(value)
                            partialSetWaitUntilTimeWindowConfig(action.id, config)
                        }}
                        onTimeRangeChange={(newTime, index) => {
                            if (isCustomTimeRange) {
                                const config = getUpdatedTimeRangeConfig(newTime, index, time)
                                partialSetWaitUntilTimeWindowConfig(action.id, config)
                            }
                        }}
                    />
                </div>

                <TimezoneConfiguration
                    timezone={timezone}
                    usePersonTimezone={use_person_timezone}
                    fallbackTimezone={fallback_timezone}
                    currentTeamTimezone={currentTeam?.timezone}
                    timezoneOptions={timezoneOptions}
                    onTimezoneChange={handleTimezoneChange}
                    onUsePersonTimezoneChange={handleUsePersonTimezoneChange}
                    onFallbackTimezoneChange={handleFallbackTimezoneChange}
                    showPersonTimezoneOption={showPersonTimezone}
                />
            </div>
        </>
    )
}

function DayConfiguration({
    day,
    isCustomDate,
    onDayChange,
    onCustomDaysChange,
}: {
    day: DayConfig
    isCustomDate: boolean
    onDayChange: (value: string) => void
    onCustomDaysChange: (newDays: WeekdayType[]) => void
}): JSX.Element {
    return (
        <div className="flex-1 flex flex-col gap-2">
            <LemonLabel>Days of week</LemonLabel>
            <LemonSelect
                value={getDaySelectValue(day)}
                onChange={onDayChange}
                options={DATE_OPTIONS}
                data-attr="date-select"
            />
            {isCustomDate && Array.isArray(day) && (
                <>
                    <LemonLabel>Custom days</LemonLabel>
                    <LemonInputSelect
                        value={day}
                        onChange={(newDays) => onCustomDaysChange(newDays as WeekdayType[])}
                        options={WEEKDAY_OPTIONS}
                        mode="multiple"
                        data-attr="custom-days-select"
                    />
                </>
            )}
        </div>
    )
}

function TimeConfiguration({
    time,
    isCustomTime,
    onTimeChange,
    onTimeRangeChange,
}: {
    time: TimeConfig
    isCustomTime: boolean
    onTimeChange: (value: string) => void
    onTimeRangeChange: (newTime: string, index: 0 | 1) => void
}): JSX.Element {
    return (
        <div className="flex-1 flex flex-col gap-2">
            <LemonLabel>Time of day</LemonLabel>
            <LemonSelect
                value={isCustomTime ? 'custom' : (time as string)}
                onChange={onTimeChange}
                options={TIME_OPTIONS}
                data-attr="time-select"
            />
            {isCustomTime && Array.isArray(time) && (
                <div className="flex flex-col gap-2">
                    <div>
                        <LemonLabel>Start time</LemonLabel>
                        <LemonSelect
                            value={time[0]}
                            onChange={(value) => onTimeRangeChange(value as string, 0)}
                            options={TIME_RANGE_OPTIONS}
                            data-attr="start-time-select"
                        />
                    </div>
                    <div>
                        <LemonLabel>End time</LemonLabel>
                        <LemonSelect
                            value={time[1]}
                            onChange={(value) => onTimeRangeChange(value as string, 1)}
                            options={TIME_RANGE_OPTIONS}
                            data-attr="end-time-select"
                        />
                    </div>
                </div>
            )}
        </div>
    )
}

function TimezoneConfiguration({
    timezone,
    usePersonTimezone,
    fallbackTimezone,
    currentTeamTimezone,
    timezoneOptions,
    onTimezoneChange,
    onUsePersonTimezoneChange,
    onFallbackTimezoneChange,
    showPersonTimezoneOption,
}: {
    timezone: string | null
    usePersonTimezone?: boolean
    fallbackTimezone?: string | null
    currentTeamTimezone?: string
    timezoneOptions: { key: string; label: string }[]
    onTimezoneChange: (timezone: string[]) => void
    onUsePersonTimezoneChange: (checked: boolean) => void
    onFallbackTimezoneChange: (timezone: string[]) => void
    showPersonTimezoneOption: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            {showPersonTimezoneOption && (
                <LemonSwitch
                    checked={usePersonTimezone ?? false}
                    onChange={onUsePersonTimezoneChange}
                    label="Use person's timezone"
                    bordered
                    tooltip="Requires the GeoIP transformation to be enabled in Data pipelines → Transformations."
                    data-attr="use-person-timezone-switch"
                />
            )}

            {showPersonTimezoneOption && usePersonTimezone ? (
                <div>
                    <LemonLabel>Fallback timezone</LemonLabel>
                    <p className="text-xs text-muted mb-2">
                        Used when the person doesn't have a timezone set (no $geoip_time_zone property)
                    </p>
                    <LemonInputSelect
                        mode="single"
                        placeholder="Select a fallback time zone"
                        value={[fallbackTimezone || timezone || currentTeamTimezone || 'UTC']}
                        popoverClassName="z-[1000]"
                        onChange={onFallbackTimezoneChange}
                        options={timezoneOptions}
                        data-attr="fallback-timezone-select"
                    />
                </div>
            ) : (
                <div>
                    <LemonLabel>Timezone</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        placeholder="Select a time zone"
                        value={[timezone || currentTeamTimezone || 'UTC']}
                        popoverClassName="z-[1000]"
                        onChange={onTimezoneChange}
                        options={timezoneOptions}
                        data-attr="timezone-select"
                    />
                </div>
            )}
        </div>
    )
}
