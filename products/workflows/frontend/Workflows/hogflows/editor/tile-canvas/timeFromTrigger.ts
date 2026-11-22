import { getEdgeId } from '../../edgeId'
import type { HogFlowAction, HogFlowEdge } from '../../types'
import { isWindowDay } from './stepPresentation'
import { ActionOf } from './stepValues'
import { shortLabel } from './tileCanvasLayout'
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
// totals use the same ceilings to name the time a run really waits.
const DELAY_CEILINGS: Record<DurationUnit, number> = { d: 365, h: 24, m: 60, s: 60 }
const WAIT_CEILINGS: Record<DurationUnit, number> = { d: 30, h: 24, m: 60, s: 60 }
const DEFAULT_DATE_WAIT_CEILING = '30d'

const DAY_SECONDS = SECONDS_PER_UNIT.d
const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6]
// The executor schedules a time window by local calendar days, and the day the clocks go back has an extra hour.
const CLOCK_CHANGE_SECONDS = SECONDS_PER_UNIT.h

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
        // A cap the executor cannot read falls back to the default.
        return upTo(
            durationSeconds(action.config.max_delay_duration, DELAY_CEILINGS) ??
                durationSeconds(DEFAULT_DATE_WAIT_CEILING, DELAY_CEILINGS)
        )
    }
    return exactly(durationSeconds(action.config.delay_duration, DELAY_CEILINGS))
}

const CLOCK_PATTERN = /^([01]?[0-9]|2[0-3]):([0-5][0-9])$/

function clockSeconds(time: unknown): number | null {
    const parts = typeof time === 'string' ? CLOCK_PATTERN.exec(time) : null
    return parts ? Number(parts[1]) * 3600 + Number(parts[2]) * 60 : null
}

function openSecondsPerDay(time: ActionOf<'wait_until_time_window'>['config']['time']): number | null {
    if (time === 'any') {
        return DAY_SECONDS
    }
    // A workflow saved through the API can hold a time range the editor would not write.
    if (!Array.isArray(time) || time.length !== 2) {
        return null
    }
    const [start, end] = time.map(clockSeconds)
    if (start === null || end === null) {
        return null
    }
    // A window whose end is not after its start wraps past midnight, as the executor reads it.
    return end > start ? end - start : DAY_SECONDS - (start - end)
}

function timeWindowWait({ config }: ActionOf<'wait_until_time_window'>): TimeFromTrigger {
    const days = WEEKDAYS.filter((weekday) => isWindowDay(config.day, weekday))
    const openSeconds = openSecondsPerDay(config.time)
    // With no day in the window the executor fails the run, so no time after it can be named.
    if (!days.length || openSeconds === null) {
        return UNKNOWN_WAIT
    }
    // The longest wait starts as the window closes and ends as it opens on the next day in the window.
    const longestGapDays = Math.max(...days.map((day, index) => (days[(index + 1) % days.length] - day + 7) % 7 || 7))
    const closedSeconds = longestGapDays * DAY_SECONDS - openSeconds
    return closedSeconds > 0 ? upTo(closedSeconds + CLOCK_CHANGE_SECONDS) : NO_WAIT
}

function conditionWait(action: ActionOf<'wait_until_condition'>, edge: HogFlowEdge): TimeFromTrigger {
    // With no timeout the executor checks the condition once and continues at once.
    if (!action.config.max_wait_duration) {
        return NO_WAIT
    }
    const timeout = durationSeconds(action.config.max_wait_duration, WAIT_CEILINGS)
    // A match can come at any moment up to the timeout. The no-match arrow runs once the timeout ends.
    return edge.type === 'branch' ? upTo(timeout) : exactly(timeout)
}

function stepWait(action: HogFlowAction | undefined, edge: HogFlowEdge): TimeFromTrigger {
    switch (action?.type) {
        case 'delay':
            return delayWait(action)
        case 'wait_until_time_window':
            return timeWindowWait(action)
        case 'wait_until_condition':
            return conditionWait(action, edge)
        default:
            return NO_WAIT
    }
}

function hasFilters(action: HogFlowAction | undefined): boolean {
    const filters = action?.filters
    return [filters?.properties, filters?.events, filters?.actions].some((list) => (list?.length ?? 0) > 0)
}

/** The time a step holds people before they take the arrow out of it. */
function waitAlong(action: HogFlowAction | undefined, edge: HogFlowEdge): TimeFromTrigger {
    const wait = stepWait(action, edge)
    // The executor skips a step whose filters a person does not match and takes the no-match arrow at once.
    return edge.type === 'continue' && hasFilters(action) ? upTo(wait.maxSeconds) : wait
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

/** The steps that an arrow leads back to from a step after them, found by a depth-first walk from the triggers. */
function loopStarts(workflow: FlowGraph, triggerIds: readonly string[]): string[] {
    const onPath = new Set<string>()
    const visited = new Set<string>()
    const starts: string[] = []
    triggerIds.forEach((triggerId) => {
        if (visited.has(triggerId)) {
            return
        }
        visited.add(triggerId)
        onPath.add(triggerId)
        const pending: [id: string, nextEdge: number][] = [[triggerId, 0]]
        while (pending.length) {
            const top = pending[pending.length - 1]
            const edge = outgoingEdges(workflow, top[0])[top[1]++]
            if (!edge) {
                onPath.delete(top[0])
                pending.pop()
            } else if (onPath.has(edge.to)) {
                starts.push(edge.to)
            } else if (!visited.has(edge.to)) {
                visited.add(edge.to)
                onPath.add(edge.to)
                pending.push([edge.to, 0])
            }
        }
    })
    return starts
}

export function timeFromTrigger(workflow: FlowGraph): TimesFromTrigger {
    const steps = new Map<string, TimeFromTrigger>()
    const edges = new Map<string, TimeFromTrigger>()
    const actionsById = new Map(workflow.actions.map((action) => [action.id, action]))
    const triggerIds = workflow.actions.filter((action) => action.type === 'trigger').map((action) => action.id)
    triggerIds.forEach((id) => steps.set(id, NO_WAIT))
    // The API allows an arrow back to an earlier step for a retry loop, so a shorter path can reach a step after
    // a pass read it. Waits are never negative, so repeating the pass settles the times within one pass per step.
    const order = executionOrder(workflow, triggerIds)
    // A person can go round a loop any number of times, so the steps from a loop onwards have no upper bound.
    const afterLoop = new Set(executionOrder(workflow, loopStarts(workflow, triggerIds)))
    let changed = true
    for (let pass = 0; changed && pass <= order.length; pass++) {
        changed = false
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
                const before = steps.get(edge.to)
                const after = spanning(before, taken)
                changed ||= !before || before.minSeconds !== after.minSeconds || before.maxSeconds !== after.maxSeconds
                steps.set(edge.to, after)
            })
        })
    }
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
    // Round up so that a wait under a second still shows, after rounding off float drift such as 1.1 * 3600.
    let rest = Math.max(1, Math.ceil(Math.round(totalSeconds * 1000) / 1000))
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
    const maxText = durationText(maxSeconds)
    if (minSeconds === 0) {
        return `Reached up to ${maxText} after the trigger`
    }
    // Two bounds that differ only in units the text leaves out read as one time.
    const minText = durationText(minSeconds)
    return minText === maxText
        ? `Reached ${maxText} after the trigger`
        : `Reached ${minText} to ${maxText} after the trigger`
}

/** The tooltip of an arrow or path label: its full text when the canvas shortens it, then the time people take it. */
export function labelTooltip(label: string | undefined, reachedAfter: string | undefined): string | undefined {
    const fullLabel = label && label !== shortLabel(label) ? label.replace(/\.$/, '') : undefined
    return [fullLabel, reachedAfter].filter(Boolean).join('. ') || undefined
}
