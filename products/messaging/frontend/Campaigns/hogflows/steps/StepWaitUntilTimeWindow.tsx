import { IconDay } from '@posthog/icons'
import { LemonLabel, LemonSelect, LemonInputSelect, LemonDivider } from '@posthog/lemon-ui'
import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'
import { teamLogic } from 'scenes/teamLogic'
import { WeekdayType } from '~/types'
import { timeZoneLabel } from 'lib/utils'

export const StepWaitUntilTimeWindow: HogFlowStep<'wait_until_time_window'> = {
    type: 'wait_until_time_window',
    name: 'Time window',
    description: 'Wait until a specific time window is reached.',
    icon: <IconDay />,
    renderNode: (props) => <StepWaitUntilTimeWindowNode {...props} />,
    renderConfiguration: (node) => <StepWaitUntilTimeWindowConfiguration node={node} />,
    create: () => {
        return {
            action: {
                name: 'Time window',
                description: '',
                type: 'wait_until_time_window',
                on_error: 'continue',
                config: {
                    timezone: null,
                    day: 'any',
                    time: 'any',
                },
            },
            branchEdges: 1,
        }
    },
}

function StepWaitUntilTimeWindowNode({ data }: HogFlowStepNodeProps): JSX.Element {
    return <StepView action={data} />
}

function StepWaitUntilTimeWindowConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'wait_until_time_window' }>>
}): JSX.Element {
    const action = node.data
    const { timezone, day, time } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)

    const options = Object.entries(preflight?.available_timezones || {}).map(([tz, offset]) => ({
        key: tz,
        label: timeZoneLabel(tz, offset),
    }))

    // Date options - using string values for LemonSelect compatibility
    const dateOptions = [
        { value: 'any', label: 'Any day' },
        { value: 'weekday', label: 'Weekdays' },
        { value: 'weekend', label: 'Weekends' },
        { value: 'custom', label: 'Specific days' },
    ]
    const isCustomDate = day !== 'any' && Array.isArray(day)

    // Time options
    const timeOptions = [
        { value: 'any', label: 'Any time' },
        { value: 'custom', label: 'Specific time range' },
    ]
    const isCustomTime = time !== 'any' && Array.isArray(time)

    // Generate time range options (00:00 to 23:00)
    const timeRangeOptions = Array.from({ length: 24 }, (_, i) => ({
        value: `${i.toString().padStart(2, '0')}:00`,
        label: `${i.toString().padStart(2, '0')}:00`,
    }))

    // Helper function to convert day value to string for LemonSelect
    const getDayValue = (dayValue: typeof day): string => {
        if (dayValue === 'any' || dayValue === 'weekday' || dayValue === 'weekend') {
            return dayValue
        }
        if (Array.isArray(dayValue)) {
            return 'custom'
        }
        return 'any'
    }

    // Helper function to convert string back to date value
    const getDayValueFromString = (value: string): typeof day => {
        switch (value) {
            case 'any':
            case 'weekday':
            case 'weekend':
                return value
            case 'custom':
                return ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
            case 'monday':
            case 'tuesday':
            case 'wednesday':
            case 'thursday':
            case 'friday':
            case 'saturday':
            case 'sunday':
                return [value]
            default:
                return 'any'
        }
    }

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-wrap">
                <div className="flex-1 flex flex-col gap-2">
                    <LemonLabel>Days of week</LemonLabel>
                    <LemonSelect
                        value={getDayValue(day)}
                        onChange={(value) => {
                            const newDayValue = getDayValueFromString(value as string)
                            setCampaignActionConfig(action.id, { day: newDayValue })
                        }}
                        options={dateOptions}
                        data-attr="date-select"
                    />
                    {isCustomDate && (
                        <>
                            <LemonLabel>Custom days</LemonLabel>
                            <LemonInputSelect
                                value={day}
                                onChange={(newDays) =>
                                    setCampaignActionConfig(action.id, { day: [...newDays] as WeekdayType[] })
                                }
                                options={[
                                    { key: 'monday', label: 'Monday' },
                                    { key: 'tuesday', label: 'Tuesday' },
                                    { key: 'wednesday', label: 'Wednesday' },
                                    { key: 'thursday', label: 'Thursday' },
                                    { key: 'friday', label: 'Friday' },
                                    { key: 'saturday', label: 'Saturday' },
                                    { key: 'sunday', label: 'Sunday' },
                                ]}
                                mode="multiple"
                                data-attr="date-select"
                            />
                        </>
                    )}
                </div>

                <LemonDivider vertical />

                <div className="flex-1 flex flex-col gap-2">
                    <LemonLabel>Time of day</LemonLabel>
                    <LemonSelect
                        value={isCustomTime ? 'custom' : time}
                        onChange={(value) => {
                            if (value === 'custom') {
                                // Default to 9 AM - 5 PM
                                setCampaignActionConfig(action.id, { time: ['09:00', '17:00'] })
                            } else {
                                setCampaignActionConfig(action.id, { time: value as 'any' | [string, string] })
                            }
                        }}
                        options={timeOptions}
                        data-attr="time-select"
                    />
                    {isCustomTime && (
                        <div className="gap-2">
                            <div>
                                <LemonLabel>Start time</LemonLabel>
                                <LemonSelect
                                    value={time[0]}
                                    onChange={(value) => {
                                        setCampaignActionConfig(action.id, { time: [value as string, time[1]] })
                                    }}
                                    options={timeRangeOptions}
                                    data-attr="start-time-select"
                                />
                            </div>
                            <div>
                                <LemonLabel>End time</LemonLabel>
                                <LemonSelect
                                    value={time[1]}
                                    onChange={(value) => {
                                        setCampaignActionConfig(action.id, { time: [time[0], value as string] })
                                    }}
                                    options={timeRangeOptions}
                                    data-attr="end-time-select"
                                />
                            </div>
                        </div>
                    )}
                </div>
            </div>
            <div>
                <LemonLabel>Timezone</LemonLabel>
                <LemonInputSelect
                    mode="single"
                    placeholder="Select a time zone"
                    value={[timezone || currentTeam?.timezone || 'UTC']}
                    popoverClassName="z-[1000]"
                    onChange={([newTimezone]): void => {
                        if (!preflight?.available_timezones) {
                            throw new Error('No timezones are available')
                        }
                        setCampaignActionConfig(action.id, { timezone: newTimezone })
                    }}
                    options={options}
                    data-attr="timezone-select"
                />
            </div>
        </div>
    )
}
