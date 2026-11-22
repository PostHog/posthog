import { getEdgeId } from '../../edgeId'
import type { HogFlowAction, HogFlowEdge } from '../../types'
import { ActionOf } from './stepValues'
import { executionOrder, FlowGraph, outgoingEdges } from './tileCanvasModel'

/** How long after the trigger a person reaches a step, over every path that leads there. */
export interface TimeFromTrigger {
    minSeconds: number
    /** Null when a wait on the way has no length the editor can read, such as a wait with no complete timeout. */
    maxSeconds: number | null
}

export interface TimesFromTrigger {
    steps: Map<string, TimeFromTrigger>
    /** Keyed by `getEdgeId`: when people take the arrow, which is when they reach the step it leads to by it. */
    edges: Map<string, TimeFromTrigger>
}

type DurationUnit = 'd' | 'h' | 'm' | 's'

const SECONDS_PER_UNIT: Record<DurationUnit, number> = { d: 86400, h: 3600, m: 60, s: 1 }
const DURATION_PATTERN = /^([0-9]+(?:\.[0-9]+)?|\.[0-9]+)([dhms])$/

// The executor holds each wait to the ceiling of its unit and stores a larger amount unchanged, so the
// totals use the same ceilings to name the time a run really waits. A fixed delay and the cap of a date
// wait use the delay ceilings; a wait for a condition uses the lower wait ceilings.
const DELAY_CEILINGS: Record<DurationUnit, number> = { d: 365, h: 24, m: 60, s: 60 }
const WAIT_CEILINGS: Record<DurationUnit, number> = { d: 30, h: 24, m: 60, s: 60 }
const DEFAULT_DATE_WAIT_CEILING = '30d'

// The executor schedules a time window by local calendar days, and the day the clocks go back has 25 hours.
const LONGEST_DAY_SECONDS = SECONDS_PER_UNIT.d + SECONDS_PER_UNIT.h
// The executor looks at most a week ahead for the next day in the window, and a clock change can add an hour.
const LONGEST_WEEK_SECONDS = 7 * SECONDS_PER_UNIT.d + SECONDS_PER_UNIT.h

const NO_WAIT: TimeFromTrigger = { minSeconds: 0, maxSeconds: 0 }
const UNKNOWN_WAIT: TimeFromTrigger = { minSeconds: 0, maxSeconds: null }

function durationSeconds(value: string | undefined | null, ceilings: Record<DurationUnit, number>): number | null {
    const parts = DURATION_PATTERN.exec(value ?? '')
    if (!parts) {
        return null
    }
    const unit = parts[2] as DurationUnit
    return Math.min(parseFloat(parts[1]), ceilings[unit]) * SECONDS_PER_UNIT[unit]
}

function exactly(seconds: number | null): TimeFromTrigger {
    return seconds === null ? UNKNOWN_WAIT : { minSeconds: seconds, maxSeconds: seconds }
}

function upTo(seconds: number | null): TimeFromTrigger {
    return { minSeconds: 0, maxSeconds: seconds }
}

function delayWait(action: ActionOf<'delay'>): TimeFromTrigger {
    if (action.config.delay_until) {
        // The date can already have passed, and the run waits no longer than the cap past the step's start.
        return upTo(durationSeconds(action.config.max_delay_duration || DEFAULT_DATE_WAIT_CEILING, DELAY_CEILINGS))
    }
    return exactly(durationSeconds(action.config.delay_duration, DELAY_CEILINGS))
}

function timeWindowWait({ config }: ActionOf<'wait_until_time_window'>): TimeFromTrigger {
    if (config.day === 'any') {
        return config.time === 'any' ? NO_WAIT : upTo(LONGEST_DAY_SECONDS)
    }
    return upTo(LONGEST_WEEK_SECONDS)
}

/** The time a step holds people before they take the arrow out of it. */
function waitAlong(action: HogFlowAction | undefined, edge: HogFlowEdge): TimeFromTrigger {
    switch (action?.type) {
        case 'delay':
            return delayWait(action)
        case 'wait_until_time_window':
            return timeWindowWait(action)
        case 'wait_until_condition': {
            const timeout = durationSeconds(action.config.max_wait_duration, WAIT_CEILINGS)
            // A match can come at any moment up to the timeout. The no-match arrow runs once the timeout ends.
            return edge.type === 'branch' ? upTo(timeout) : exactly(timeout)
        }
        default:
            return NO_WAIT
    }
}

function plus(a: TimeFromTrigger, b: TimeFromTrigger): TimeFromTrigger {
    return {
        minSeconds: a.minSeconds + b.minSeconds,
        maxSeconds: a.maxSeconds === null || b.maxSeconds === null ? null : a.maxSeconds + b.maxSeconds,
    }
}

function spanning(a: TimeFromTrigger | undefined, b: TimeFromTrigger): TimeFromTrigger {
    if (!a) {
        return b
    }
    return {
        minSeconds: Math.min(a.minSeconds, b.minSeconds),
        maxSeconds: a.maxSeconds === null || b.maxSeconds === null ? null : Math.max(a.maxSeconds, b.maxSeconds),
    }
}

export function timeFromTrigger(workflow: FlowGraph): TimesFromTrigger {
    const steps = new Map<string, TimeFromTrigger>()
    const edges = new Map<string, TimeFromTrigger>()
    const actionsById = new Map(workflow.actions.map((action) => [action.id, action]))
    const triggerIds = workflow.actions.filter((action) => action.type === 'trigger').map((action) => action.id)
    triggerIds.forEach((id) => steps.set(id, NO_WAIT))
    // Each step comes before the steps it leads to, so every path into a step is counted before the step is read.
    // The one exception is an arrow back to an earlier step, which the API allows to build a retry loop.
    const order = executionOrder(workflow, triggerIds)
    const position = new Map(order.map((id, index) => [id, index]))
    const isLoopBack = (edge: HogFlowEdge): boolean => (position.get(edge.to) ?? 0) <= (position.get(edge.from) ?? 0)
    const loopStarts = order.flatMap((id) =>
        outgoingEdges(workflow, id)
            .filter(isLoopBack)
            .map((edge) => edge.to)
    )
    // A person can go round a loop any number of times, so the steps from a loop onwards have no upper bound.
    const afterLoop = new Set(executionOrder(workflow, loopStarts))
    order.forEach((id) => {
        const counted = steps.get(id)
        if (!counted) {
            return
        }
        const reached = afterLoop.has(id) ? { ...counted, maxSeconds: null } : counted
        steps.set(id, reached)
        outgoingEdges(workflow, id).forEach((edge) => {
            const taken = plus(reached, waitAlong(actionsById.get(id), edge))
            edges.set(getEdgeId(edge), taken)
            steps.set(edge.to, spanning(steps.get(edge.to), taken))
        })
    })
    return { steps, edges }
}

const UNIT_NAMES: [seconds: number, one: string, many: string][] = [
    [SECONDS_PER_UNIT.d, 'day', 'days'],
    [SECONDS_PER_UNIT.h, 'hour', 'hours'],
    [SECONDS_PER_UNIT.m, 'minute', 'minutes'],
    [SECONDS_PER_UNIT.s, 'second', 'seconds'],
]

/** The two largest units of a duration, such as "1 day 4 hours". */
function durationText(totalSeconds: number): string {
    // Round up so that a wait under a second still names a time. The rounding to milliseconds first keeps a
    // floating point product such as 1.1 * 3600 = 3960.0000000000005 from gaining a second.
    let rest = Math.ceil(Math.round(totalSeconds * 1000) / 1000)
    const parts: string[] = []
    for (const [seconds, one, many] of UNIT_NAMES) {
        const count = Math.floor(rest / seconds)
        rest -= count * seconds
        if (count > 0 && parts.length < 2) {
            parts.push(`${count} ${count === 1 ? one : many}`)
        }
    }
    return parts.join(' ')
}

/** The sentence a step or arrow shows for its time from the trigger, or nothing when people reach it at once. */
export function reachedAfterTriggerText(time: TimeFromTrigger | undefined): string | undefined {
    if (!time) {
        return undefined
    }
    const { minSeconds, maxSeconds } = time
    if (maxSeconds === null) {
        return minSeconds > 0 ? `Reached ${durationText(minSeconds)} or more after the trigger` : undefined
    }
    if (maxSeconds === 0) {
        return undefined
    }
    if (minSeconds === maxSeconds) {
        return `Reached ${durationText(maxSeconds)} after the trigger`
    }
    if (minSeconds === 0) {
        return `Reached up to ${durationText(maxSeconds)} after the trigger`
    }
    return `Reached ${durationText(minSeconds)} to ${durationText(maxSeconds)} after the trigger`
}
