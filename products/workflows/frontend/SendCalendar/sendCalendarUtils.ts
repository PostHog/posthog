import { RRule } from 'rrule'

import { dayjs } from 'lib/dayjs'

import type {
    HogFlowBatchJobApi,
    HogFlowMinimalApi,
    HogFlowScheduleApi,
    UserBasicApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { describeRepeat } from '../Broadcasts/broadcastNextSend'
import { fakeUtcToReal, isOneTimeSchedule } from '../Workflows/hogflows/steps/components/rrule-helpers'
import { SCHEDULED_TRIGGER_TYPES } from '../Workflows/hogflows/steps/types'

export type CalendarView = 'month' | 'week'
export type CalendarTypeFilter = 'all' | 'broadcasts' | 'workflows'
export type CalendarSendKind = 'broadcast' | 'workflow'
export type CalendarSendState = 'planned' | 'paused' | 'sending' | 'sent' | 'failed'

export interface ScheduledEmailFlow {
    flow: HogFlowMinimalApi
    schedules: HogFlowScheduleApi[]
    batchJobs: HogFlowBatchJobApi[]
}

export interface CalendarSend {
    key: string
    flowId: string
    name: string
    kind: CalendarSendKind
    state: CalendarSendState
    at: dayjs.Dayjs
    /** "Once" or the repeat rule. Null for a run without a schedule, such as a broadcast sent right away. */
    repeat: string | null
    isRecurring: boolean
    createdBy: UserBasicApi | null
}

/** From the start of the first day to the start of the day after the last day, in the project time zone. */
export interface CalendarRange {
    start: dayjs.Dayjs
    end: dayjs.Dayjs
}

// The server allows one run per hour at most, so one schedule can put about 1,000 sends in a 6-week grid.
// Stop at a number that the grid can still show.
const MAX_SENDS_PER_SCHEDULE = 200

export function isScheduledEmailFlow(flow: Pick<HogFlowMinimalApi, 'status' | 'trigger' | 'actions'>): boolean {
    const triggerType = (flow.trigger as { type?: string } | null)?.type ?? ''
    const actions = Array.isArray(flow.actions) ? (flow.actions as ({ type?: string } | null)[]) : []
    return (
        flow.status === 'active' &&
        SCHEDULED_TRIGGER_TYPES.includes(triggerType) &&
        actions.some((action) => action?.type === 'function_email')
    )
}

export function matchesTypeFilter(
    flow: Pick<HogFlowMinimalApi, 'origin_product'>,
    filter: CalendarTypeFilter
): boolean {
    if (filter === 'all') {
        return true
    }
    return (flow.origin_product === 'broadcasts') === (filter === 'broadcasts')
}

/** The send times of a schedule inside a range, as real moments. */
export function scheduleSendTimes(
    schedule: Pick<HogFlowScheduleApi, 'rrule' | 'starts_at' | 'timezone'>,
    range: CalendarRange
): dayjs.Dayjs[] {
    const timezone = schedule.timezone || 'UTC'
    // RRule expands dates in "fake UTC": the UTC fields hold the wall-clock time in the schedule time
    // zone. That keeps a 09:00 send at 09:00 local time across a DST change, as the scheduler does.
    const toFakeUtc = (time: dayjs.Dayjs): Date => {
        const local = time.tz(timezone)
        return new Date(
            Date.UTC(local.year(), local.month(), local.date(), local.hour(), local.minute(), local.second())
        )
    }
    try {
        const rule = new RRule({ ...RRule.parseString(schedule.rrule), dtstart: toFakeUtc(dayjs(schedule.starts_at)) })
        return rule
            .between(toFakeUtc(range.start), toFakeUtc(range.end), true, (_, index) => index < MAX_SENDS_PER_SCHEDULE)
            .map((date) => fakeUtcToReal(date, timezone))
            .filter((time) => !time.isBefore(range.start) && time.isBefore(range.end))
    } catch {
        return []
    }
}

export function calendarSendsForFlow(
    { flow, schedules, batchJobs }: ScheduledEmailFlow,
    range: CalendarRange,
    now: dayjs.Dayjs
): CalendarSend[] {
    const base = {
        flowId: flow.id,
        name: flow.name || 'Untitled',
        kind: (flow.origin_product === 'broadcasts' ? 'broadcast' : 'workflow') as CalendarSendKind,
        createdBy: flow.created_by ?? null,
    }
    const sends: CalendarSend[] = []
    // A schedule shows only the sends still to come. An occurrence in the past is not proof that a send
    // went out, so past sends come from the batch jobs instead.
    const future: CalendarRange = { start: now.isAfter(range.start) ? now : range.start, end: range.end }
    if (future.start.isBefore(future.end)) {
        for (const schedule of schedules) {
            if (schedule.status === 'completed') {
                continue
            }
            const repeat = describeRepeat(schedule)
            const isRecurring = !isOneTimeSchedule(schedule.rrule)
            for (const at of scheduleSendTimes(schedule, future)) {
                sends.push({
                    ...base,
                    key: `${schedule.id}:${at.valueOf()}`,
                    state: schedule.status === 'paused' ? 'paused' : 'planned',
                    at,
                    repeat,
                    isRecurring,
                })
            }
        }
    }
    for (const job of batchJobs) {
        const at = dayjs(job.created_at)
        if (at.isBefore(range.start) || !at.isBefore(range.end)) {
            continue
        }
        sends.push({ ...base, key: job.id, state: batchJobState(job.status), at, repeat: null, isRecurring: false })
    }
    return sends
}

function batchJobState(status: HogFlowBatchJobApi['status']): CalendarSendState {
    if (status === 'completed') {
        return 'sent'
    }
    if (status === 'failed' || status === 'cancelled') {
        return 'failed'
    }
    return 'sending'
}

/** The days that the grid shows, as YYYY-MM-DD. A month view starts and ends on full weeks. */
export function calendarDays(view: CalendarView, anchor: string, weekStartDay: number): string[] {
    // Calendar dates have no time zone, so the arithmetic runs in UTC, where every day has 24 hours.
    const anchorDay = dayjs.utc(anchor)
    const first = view === 'month' ? anchorDay.startOf('month') : anchorDay
    const offset = (first.day() - weekStartDay + 7) % 7
    const gridStart = first.subtract(offset, 'day')
    const length = view === 'week' ? 7 : Math.ceil((offset + first.daysInMonth()) / 7) * 7
    return Array.from({ length }, (_, index) => gridStart.add(index, 'day').format('YYYY-MM-DD'))
}

export function calendarRange(days: string[], timezone: string): CalendarRange {
    const dayAfterLast = dayjs
        .utc(days[days.length - 1])
        .add(1, 'day')
        .format('YYYY-MM-DD')
    return { start: dayjs.tz(days[0], timezone), end: dayjs.tz(dayAfterLast, timezone) }
}

export function shiftAnchor(view: CalendarView, anchor: string, direction: 1 | -1): string {
    return dayjs.utc(anchor).add(direction, view).format('YYYY-MM-DD')
}

export function periodLabel(view: CalendarView, anchor: string, days: string[]): string {
    if (view === 'month') {
        return dayjs.utc(anchor).format('MMMM YYYY')
    }
    const first = dayjs.utc(days[0])
    const last = dayjs.utc(days[days.length - 1])
    if (first.year() !== last.year()) {
        return `${first.format('MMM D, YYYY')} to ${last.format('MMM D, YYYY')}`
    }
    if (first.month() !== last.month()) {
        return `${first.format('MMM D')} to ${last.format('MMM D, YYYY')}`
    }
    return `${first.format('MMM D')} to ${last.format('D, YYYY')}`
}

export function groupSendsByDay(sends: CalendarSend[], timezone: string): Record<string, CalendarSend[]> {
    const byDay: Record<string, CalendarSend[]> = {}
    for (const send of [...sends].sort((a, b) => a.at.valueOf() - b.at.valueOf())) {
        const day = send.at.tz(timezone).format('YYYY-MM-DD')
        ;(byDay[day] ??= []).push(send)
    }
    return byDay
}
