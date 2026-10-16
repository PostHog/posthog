import type { HogFlowScheduleApi } from 'products/workflows/frontend/generated/api.schemas'

import {
    isOneTimeSchedule,
    parseRRuleToState,
    scheduleToText,
} from '../Workflows/hogflows/steps/components/rrule-helpers'

type NextSendSchedule = Pick<HogFlowScheduleApi, 'rrule' | 'starts_at' | 'status' | 'next_run_at'>

/** The schedule behind the next send: the active one that sends first, else a paused one, so a stopped cadence still shows. */
export function pickNextSchedule<T extends NextSendSchedule>(schedules: T[]): T | null {
    const active = schedules.filter((schedule) => schedule.status === 'active')
    if (active.length > 0) {
        return active.reduce((first, schedule) => (sendsBefore(schedule, first) ? schedule : first))
    }
    return schedules.find((schedule) => schedule.status === 'paused') ?? null
}

export function nextSendTime(schedule: NextSendSchedule): string | null {
    // The scheduler sets next_run_at on its first poll after a create or an edit. A one-time
    // schedule sends at its start, so the start is the next send until then.
    return schedule.next_run_at ?? (isOneTimeSchedule(schedule.rrule) ? schedule.starts_at : null)
}

export function describeRepeat(schedule: Pick<HogFlowScheduleApi, 'rrule' | 'starts_at'>): string {
    if (isOneTimeSchedule(schedule.rrule)) {
        return 'Once'
    }
    const text = scheduleToText(parseRRuleToState(schedule.rrule), schedule.starts_at)
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Repeats'
}

function sendsBefore(a: NextSendSchedule, b: NextSendSchedule): boolean {
    const aTime = nextSendTime(a)
    const bTime = nextSendTime(b)
    if (!aTime || !bTime) {
        // A known time sorts before an unknown one.
        return !!aTime
    }
    return Date.parse(aTime) < Date.parse(bTime)
}
