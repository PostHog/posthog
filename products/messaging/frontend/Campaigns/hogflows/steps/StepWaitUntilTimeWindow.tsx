import { IconDay } from '@posthog/icons'
import { LemonLabel, LemonSelect, LemonInputSelect } from '@posthog/lemon-ui'
import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowAction } from '../types'
import { StepView } from './components/StepView'
import { HogFlowStep, HogFlowStepNodeProps } from './types'
import { tzLabel } from 'scenes/settings/environment/TimezoneConfig'
import { teamLogic } from 'scenes/teamLogic'

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
                    timezone: 'UTC',
                    date: 'any',
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
    const { timezone, date, time } = action.config

    const { setCampaignActionConfig } = useActions(hogFlowEditorLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentTeam } = useValues(teamLogic)

    const options = Object.entries(preflight?.available_timezones || {}).map(([tz, offset]) => ({
        key: tz,
        label: tzLabel(tz, offset),
    }))

    // Date options - using string values for LemonSelect compatibility
    const dateOptions = [
        { value: 'any', label: 'Any day' },
        { value: 'weekday', label: 'Weekdays' },
        { value: 'weekend', label: 'Weekends' },
        { value: 'custom', label: 'Specific days' },
    ]

    // Time options
    const timeOptions = [
        { value: 'any', label: 'Any time' },
        { value: 'custom', label: 'Custom time range' },
    ]

    // Generate time range options (00:00 to 23:00)
    const timeRangeOptions = Array.from({ length: 24 }, (_, i) => ({
        value: `${i.toString().padStart(2, '0')}:00`,
        label: `${i.toString().padStart(2, '0')}:00`,
    }))

    const isCustomTime = time !== 'any' && Array.isArray(time)

    // Helper function to convert date value to string for LemonSelect
    const getDateValue = (dateValue: typeof date): string => {
        if (dateValue === 'any' || dateValue === 'weekday' || dateValue === 'weekend') {
            return dateValue
        }
        if (Array.isArray(dateValue)) {
            if (dateValue.length === 1) {
                return dateValue[0]
            }
            if (dateValue.length === 2 && dateValue.includes('saturday') && dateValue.includes('sunday')) {
                return 'weekends_custom'
            }
            if (
                dateValue.length === 5 &&
                dateValue.includes('monday') &&
                dateValue.includes('tuesday') &&
                dateValue.includes('wednesday') &&
                dateValue.includes('thursday') &&
                dateValue.includes('friday')
            ) {
                return 'weekdays_custom'
            }
        }
        return 'any'
    }

    // Helper function to convert string back to date value
    const getDateValueFromString = (value: string): typeof date => {
        switch (value) {
            case 'any':
            case 'weekday':
            case 'weekend':
                return value
            case 'weekdays_custom':
                return ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
            case 'weekends_custom':
                return ['saturday', 'sunday']
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
        <div className="gap-4">
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

            <div>
                <LemonLabel>Days of the week</LemonLabel>
                <LemonSelect
                    value={getDateValue(date)}
                    onChange={(value) => {
                        const newDateValue = getDateValueFromString(value as string)
                        setCampaignActionConfig(action.id, { date: newDateValue })
                    }}
                    options={dateOptions}
                    data-attr="date-select"
                />
            </div>

            <div>
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
            </div>

            {isCustomTime && (
                <div className="space-y-2">
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
    )
}
