import { actions, connect, kea, key, listeners, path, props } from 'kea'

import { WeekdayType } from '~/types'

import { WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import type { stepWaitUntilTimeWindowLogicType } from './stepWaitUntilTimeWindowLogicType'

type DayConfig = 'any' | 'weekday' | 'weekend' | WeekdayType[]
type TimeConfig = 'any' | [string, string]

export type WaitUntilTimeWindowConfig = {
    timezone?: string | null
    use_person_timezone?: boolean
    fallback_timezone?: string | null
    day?: DayConfig
    time?: TimeConfig
}

const AUTO_DESCRIPTION_REGEX = /^Wait until .+ (at any time|between .+ and .+) \((.+)\)\.$/
const LEGACY_DEFAULT_DESCRIPTION = 'Wait until a specified time window.'

function capitalize(str: string): string {
    return str.charAt(0).toUpperCase() + str.slice(1)
}

function getDayDescription(day: DayConfig): string {
    if (day === 'any') {
        return 'any day'
    }
    if (day === 'weekday') {
        return 'weekdays'
    }
    if (day === 'weekend') {
        return 'weekends'
    }
    if (Array.isArray(day)) {
        if (day.length === 0) {
            return 'no days'
        }
        return day.map(capitalize).join(', ')
    }
    return 'any day'
}

function getTimeDescription(time: TimeConfig): string {
    if (time === 'any') {
        return 'any time'
    }
    if (Array.isArray(time)) {
        return `between ${time[0]} and ${time[1]}`
    }
    return 'any time'
}

export function getWaitUntilTimeWindowDescription(
    day: DayConfig,
    time: TimeConfig,
    timezone: string | null,
    usePersonTimezone?: boolean,
    fallbackTimezone?: string | null
): string {
    const dayDesc = getDayDescription(day)
    const timeDesc = getTimeDescription(time)
    // Use "at" only for "any time", otherwise use the time description directly (e.g., "between X and Y")
    const timeClause = time === 'any' ? `at ${timeDesc}` : timeDesc

    let tzDesc: string
    if (usePersonTimezone) {
        const fallback = fallbackTimezone || timezone || 'UTC'
        tzDesc = `person's timezone, fallback: ${fallback}`
    } else {
        tzDesc = timezone || 'UTC'
    }

    return `Wait until ${dayDesc} ${timeClause} (${tzDesc}).`
}

export function shouldAutoUpdateDescription(description: string): boolean {
    return (
        description.trim() === '' ||
        AUTO_DESCRIPTION_REGEX.test(description) ||
        description === LEGACY_DEFAULT_DESCRIPTION
    )
}

export type StepWaitUntilTimeWindowLogicProps = {
    workflowLogicProps: WorkflowLogicProps
}

export const stepWaitUntilTimeWindowLogic = kea<stepWaitUntilTimeWindowLogicType>([
    path((key) => [
        'products',
        'workflows',
        'frontend',
        'Workflows',
        'hogflows',
        'steps',
        'stepWaitUntilTimeWindowLogic',
        key,
    ]),
    props({} as StepWaitUntilTimeWindowLogicProps),
    key(({ workflowLogicProps }: StepWaitUntilTimeWindowLogicProps) => workflowLogicProps.id || 'new'),
    connect(({ workflowLogicProps }: StepWaitUntilTimeWindowLogicProps) => ({
        values: [workflowLogic(workflowLogicProps), ['workflow']],
        actions: [workflowLogic(workflowLogicProps), ['partialSetWorkflowActionConfig', 'setWorkflowAction']],
    })),
    actions({
        partialSetWaitUntilTimeWindowConfig: (actionId: string, config: WaitUntilTimeWindowConfig) => ({
            actionId,
            config,
        }),
    }),
    listeners(({ values, actions }) => ({
        partialSetWaitUntilTimeWindowConfig: ({ actionId, config }) => {
            actions.partialSetWorkflowActionConfig(actionId, config)

            const action = values.workflow.actions.find((a) => a.id === actionId)
            if (!action || action.type !== 'wait_until_time_window') {
                return
            }

            const currentConfig = action.config as {
                day: DayConfig
                time: TimeConfig
                timezone: string | null
                use_person_timezone?: boolean
                fallback_timezone?: string | null
            }
            const newDay = config.day ?? currentConfig.day
            const newTime = config.time ?? currentConfig.time
            const newTimezone = config.timezone !== undefined ? config.timezone : currentConfig.timezone
            const newUsePersonTimezone =
                config.use_person_timezone !== undefined
                    ? config.use_person_timezone
                    : currentConfig.use_person_timezone
            const newFallbackTimezone =
                config.fallback_timezone !== undefined ? config.fallback_timezone : currentConfig.fallback_timezone

            if (shouldAutoUpdateDescription(action.description)) {
                actions.setWorkflowAction(actionId, {
                    ...action,
                    description: getWaitUntilTimeWindowDescription(
                        newDay,
                        newTime,
                        newTimezone,
                        newUsePersonTimezone,
                        newFallbackTimezone
                    ),
                })
            }
        },
    })),
])
