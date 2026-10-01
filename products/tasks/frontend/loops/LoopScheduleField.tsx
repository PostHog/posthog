import { ChangeEvent } from 'react'

import { Input, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { LoopSchedule, LoopScheduleFrequency, WEEKDAY_NAMES } from './loopForm'

const FREQUENCY_OPTIONS: { value: LoopScheduleFrequency; label: string }[] = [
    { value: 'hourly', label: 'Every hour' },
    { value: 'daily', label: 'Every day' },
    { value: 'weekdays', label: 'Every weekday' },
    { value: 'weekly', label: 'Every week' },
]

const WEEKDAY_OPTIONS = ['1', '2', '3', '4', '5', '6', '0'].map((value) => ({
    value,
    label: `On ${WEEKDAY_NAMES[value]}`,
}))

export interface LoopScheduleFieldProps {
    schedule: LoopSchedule
    timezone: string
    disabled?: boolean
    onChange: (schedule: LoopSchedule) => void
}

export function LoopScheduleField({ schedule, timezone, disabled, onChange }: LoopScheduleFieldProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
                <Select<LoopScheduleFrequency>
                    items={FREQUENCY_OPTIONS}
                    value={schedule.frequency}
                    onValueChange={(frequency: LoopScheduleFrequency | null) =>
                        frequency && onChange({ ...schedule, frequency })
                    }
                    disabled={disabled}
                >
                    <SelectTrigger aria-label="How often" data-attr="loop-schedule-frequency">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        {FREQUENCY_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
                {schedule.frequency === 'weekly' && (
                    <Select<string>
                        items={WEEKDAY_OPTIONS}
                        value={schedule.weekday}
                        onValueChange={(weekday: string | null) => weekday && onChange({ ...schedule, weekday })}
                        disabled={disabled}
                    >
                        <SelectTrigger aria-label="Day of the week" data-attr="loop-schedule-weekday">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {WEEKDAY_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                    {option.label}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                )}
                {schedule.frequency !== 'hourly' && (
                    <Input
                        type="time"
                        className="w-32"
                        aria-label="Time"
                        value={schedule.time}
                        disabled={disabled}
                        onChange={(event: ChangeEvent<HTMLInputElement>) =>
                            event.target.value && onChange({ ...schedule, time: event.target.value })
                        }
                        data-attr="loop-schedule-time"
                    />
                )}
            </div>
            <Text size="xs" variant="muted">
                {`Times use the ${timezone} time zone.`}
            </Text>
        </div>
    )
}
