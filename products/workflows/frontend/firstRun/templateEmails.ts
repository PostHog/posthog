import type { EmailTemplate } from 'scenes/hog-functions/email-templater/types'

import { DurationUnit, parseDuration } from '../Workflows/hogflows/steps/durations'
import { getDurationText } from '../Workflows/hogflows/steps/stepDelayLogic'
import { isEmailAction } from '../Workflows/hogflows/steps/types'
import type { HogFlowAction, HogFlowEdge } from '../Workflows/hogflows/types'
import { getOrderedActions } from '../Workflows/templates/workflowTemplateDisplay'

export interface TemplateEmail {
    id: string
    subject: string
    timing: string
    email: EmailTemplate
}

const SECONDS_PER_UNIT: Record<DurationUnit, number> = { d: 86400, h: 3600, m: 60, s: 1 }

function durationSeconds(duration: unknown): number {
    const parsed = typeof duration === 'string' ? parseDuration(duration) : null
    return parsed ? parsed.amount * SECONDS_PER_UNIT[parsed.unit] : 0
}

function describeTiming(seconds: number): string {
    if (seconds <= 0) {
        return 'Right away'
    }
    const unit =
        (['d', 'h', 'm'] as DurationUnit[]).find((candidate) => seconds % SECONDS_PER_UNIT[candidate] === 0) ?? 's'
    return `After ${getDurationText(`${seconds / SECONDS_PER_UNIT[unit]}${unit}`)}`
}

// Seconds between the trigger and each step, summed over the delays on the first path that reaches it.
function delaysFromTrigger(actions: HogFlowAction[], edges: HogFlowEdge[]): Map<string, number> {
    const actionsById = new Map(actions.map((action) => [action.id, action]))
    const trigger = actions.find((action) => action.type === 'trigger')
    const delays = new Map<string, number>()
    if (!trigger) {
        return delays
    }
    delays.set(trigger.id, 0)
    const queue = [trigger.id]
    for (let cursor = 0; cursor < queue.length; cursor++) {
        const from = queue[cursor]
        for (const edge of edges.filter((edge) => edge.from === from)) {
            if (delays.has(edge.to)) {
                continue
            }
            const target = actionsById.get(edge.to)
            const ownDelay = target?.type === 'delay' ? durationSeconds(target.config.delay_duration) : 0
            delays.set(edge.to, (delays.get(from) ?? 0) + ownDelay)
            queue.push(edge.to)
        }
    }
    return delays
}

export function listTemplateEmails(actions: HogFlowAction[], edges: HogFlowEdge[]): TemplateEmail[] {
    const delays = delaysFromTrigger(actions, edges)
    return getOrderedActions(actions, edges)
        .filter(isEmailAction)
        .map((action) => {
            const email = action.config.inputs.email?.value as EmailTemplate
            return {
                id: action.id,
                subject: email?.subject ?? '',
                timing: describeTiming(delays.get(action.id) ?? 0),
                email,
            }
        })
}
