import { RRule } from 'rrule'

import { dayjs } from 'lib/dayjs'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import type {
    HogFlowScheduleApi,
    SendCalendarBatchJobApi,
    SendCalendarFlowApi,
    UserBasicApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { audienceCohortIds } from '../Broadcasts/audience/audienceList'
import { manageDisabledReason } from '../Broadcasts/broadcastLifecycle'
import {
    fakeUtcToReal,
    ONE_TIME_RRULE,
    isOneTimeSchedule,
    parseRRuleToState,
    scheduleToText,
    stateToRRule,
} from '../Workflows/hogflows/steps/components/rrule-helpers'

export type CalendarView = 'month' | 'week'
export type CalendarTypeFilter = 'all' | 'broadcasts' | 'workflows'
export type CalendarSendKind = 'broadcast' | 'workflow'
export type CalendarSendState = 'planned' | 'paused' | 'sending' | 'sent' | 'failed'

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
    /** The schedule behind a planned or paused send. Null for a past run. */
    schedule: HogFlowScheduleApi | null
    userAccessLevel: string | null
    audience: SendAudience
    /** The message category of the email, which decides who can opt out of it. */
    categoryId: string | null
}

/** Who the sends of a flow go to. */
export interface SendAudience {
    /** The cohorts that the audience filters on, once each. */
    cohortIds: number[]
    /** The other audience filters, such as person properties. */
    filters: AnyPropertyFilter[]
    /** True when the flow runs once for each matching account, not for each person. */
    accounts: boolean
    /** The "To" address of the email. Only a schedule trigger uses it, because that trigger has no audience. */
    address: string | null
}

/** From the start of the first day to the start of the day after the last day, in the project time zone. */
export interface CalendarRange {
    start: dayjs.Dayjs
    end: dayjs.Dayjs
}

// The server allows one run per hour at most, so one schedule can put about 1,000 sends in a 6-week grid.
// Stop at a number that the grid can still show.
const MAX_SENDS_PER_SCHEDULE = 200

export function sendAudience(
    flow: Pick<SendCalendarFlowApi, 'trigger_type' | 'audience_properties' | 'audience_type' | 'email_to'>
): SendAudience {
    if (flow.trigger_type !== 'batch') {
        return { cohortIds: [], filters: [], accounts: false, address: flow.email_to || null }
    }
    return audienceFromProperties(
        flow.audience_properties as unknown as AnyPropertyFilter[],
        flow.audience_type === 'accounts'
    )
}

export function audienceFromProperties(properties: AnyPropertyFilter[], accounts = false): SendAudience {
    // An excluded cohort says nothing about who else the audience reaches, so it counts like any other filter.
    const isCohortInclusion = (filter: AnyPropertyFilter): boolean =>
        filter.type === PropertyFilterType.Cohort && filter.operator !== PropertyOperator.NotIn
    return {
        cohortIds: audienceCohortIds(properties.filter(isCohortInclusion)),
        filters: properties.filter((filter) => !isCohortInclusion(filter)),
        accounts,
        address: null,
    }
}

export function matchesTypeFilter(
    flow: Pick<SendCalendarFlowApi, 'origin_product'>,
    filter: CalendarTypeFilter
): boolean {
    if (filter === 'all') {
        return true
    }
    return (flow.origin_product === 'broadcasts') === (filter === 'broadcasts')
}

/** A rule in one spelling, so two spellings of the same rule compare equal. The start date is not part of it. */
function normalizedRule(rrule: string): string | null {
    try {
        const { dtstart: _dtstart, ...options } = RRule.parseString(rrule)
        const text = new RRule({ ...options, interval: options.interval ?? 1 }).toString().replace('RRULE:', '')
        return text.split(';').sort().join(';')
    } catch {
        return null
    }
}

/** Whether the schedule editor can hold the rule. Other rules, such as hourly ones from the API, come back changed. */
function fitsScheduleEditor(schedule: Pick<HogFlowScheduleApi, 'rrule' | 'starts_at'>): boolean {
    const original = normalizedRule(schedule.rrule)
    return (
        original !== null &&
        normalizedRule(stateToRRule(parseRRuleToState(schedule.rrule), schedule.starts_at)) === original
    )
}

export function describeRepeat(schedule: Pick<HogFlowScheduleApi, 'rrule' | 'starts_at'>): string {
    if (isOneTimeSchedule(schedule.rrule)) {
        return 'Once'
    }
    const text = fitsScheduleEditor(schedule)
        ? scheduleToText(parseRRuleToState(schedule.rrule), schedule.starts_at)
        : normalizedRule(schedule.rrule) !== null
          ? new RRule(RRule.parseString(schedule.rrule)).toText()
          : ''
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : 'Repeats'
}

/** The send times of a schedule inside a range, as real moments. */
export function scheduleSendTimes(
    schedule: Pick<HogFlowScheduleApi, 'rrule' | 'starts_at' | 'timezone'>,
    range: CalendarRange,
    maxSends: number = MAX_SENDS_PER_SCHEDULE
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
            .between(toFakeUtc(range.start), toFakeUtc(range.end), true, (_, index) => index < maxSends)
            .map((date) => fakeUtcToReal(date, timezone))
            .filter((time) => !time.isBefore(range.start) && time.isBefore(range.end))
    } catch {
        return []
    }
}

export function calendarSendsForFlow(
    flow: SendCalendarFlowApi,
    range: CalendarRange,
    now: dayjs.Dayjs,
    maxSendsPerSchedule: number = MAX_SENDS_PER_SCHEDULE
): CalendarSend[] {
    const base = {
        flowId: flow.id,
        name: flow.name || 'Untitled',
        kind: (flow.origin_product === 'broadcasts' ? 'broadcast' : 'workflow') as CalendarSendKind,
        createdBy: flow.created_by ?? null,
        userAccessLevel: flow.user_access_level ?? null,
        audience: sendAudience(flow),
        categoryId: flow.message_category_id,
    }
    const sends: CalendarSend[] = []
    // A schedule shows only the sends still to come. An occurrence in the past is not proof that a send
    // went out, so past sends come from the batch jobs instead.
    const future: CalendarRange = { start: now.isAfter(range.start) ? now : range.start, end: range.end }
    if (future.start.isBefore(future.end)) {
        for (const schedule of flow.schedules) {
            if (schedule.status === 'completed') {
                continue
            }
            const repeat = describeRepeat(schedule)
            const isRecurring = !isOneTimeSchedule(schedule.rrule)
            for (const at of scheduleSendTimes(schedule, future, maxSendsPerSchedule)) {
                sends.push({
                    ...base,
                    key: `${schedule.id}:${at.valueOf()}`,
                    state: schedule.status === 'paused' ? 'paused' : 'planned',
                    at,
                    repeat,
                    isRecurring,
                    schedule,
                })
            }
        }
    }
    for (const job of flow.batch_jobs) {
        const at = dayjs(job.created_at)
        if (at.isBefore(range.start) || !at.isBefore(range.end)) {
            continue
        }
        sends.push({
            ...base,
            key: job.id,
            state: batchJobState(job.status),
            at,
            repeat: null,
            isRecurring: false,
            schedule: null,
        })
    }
    return sends
}

function batchJobState(status: SendCalendarBatchJobApi['status']): CalendarSendState {
    if (status === 'completed') {
        return 'sent'
    }
    if (status === 'failed' || status === 'cancelled') {
        return 'failed'
    }
    return 'sending'
}

/** Why a send cannot move with drag and drop, or null when it can. */
export function moveBlockedReason(
    send: Pick<CalendarSend, 'state' | 'schedule' | 'userAccessLevel' | 'at'>,
    now: dayjs.Dayjs = dayjs()
): string | null {
    // The calendar loads once, so a send can show as planned after its time passed. Moving it would send it again.
    if (send.state === 'sent' || send.state === 'failed' || !send.at.isAfter(now)) {
        return 'This send already went out.'
    }
    if (send.state === 'sending') {
        return 'This send is in progress.'
    }
    if (send.state === 'paused' || !send.schedule) {
        return 'This schedule is paused. Open it to schedule it again.'
    }
    const accessReason = manageDisabledReason(send.userAccessLevel)
    if (accessReason) {
        return accessReason
    }
    if (!isOneTimeSchedule(send.schedule.rrule)) {
        if (!fitsScheduleEditor(send.schedule)) {
            return 'Open the schedule to move a send that repeats this way.'
        }
        const state = parseRRuleToState(send.schedule.rrule)
        // Shifting the weekdays keeps a weekly cadence. Other repeat rules have no single shift that keeps
        // their pattern, for example "the last day of the month". Every N weeks keeps its pattern only with
        // one weekday: with two, a shift across the week start moves one of them into the skipped week.
        if (state.frequency !== 'weekly' || (state.interval !== 1 && state.weekdays.length !== 1)) {
            return 'Open the schedule to move a send that repeats this way.'
        }
    }
    return null
}

/** Moves a time by whole calendar days, so it keeps its wall-clock time in the time zone across a DST change. */
function shiftDays(time: dayjs.Dayjs, days: number, timezone: string): dayjs.Dayjs {
    const local = time.tz(timezone)
    const date = dayjs.utc(local.format('YYYY-MM-DD')).add(days, 'day').format('YYYY-MM-DD')
    return dayjs.tz(`${date} ${local.format('HH:mm:ss')}`, timezone)
}

/** Where a send lands when someone drops it on a day, or null when that day cannot take it. */
export function dropTarget(
    send: Pick<CalendarSend, 'at' | 'schedule'>,
    day: string,
    timezone: string,
    now: dayjs.Dayjs
): { days: number; at: dayjs.Dayjs } | null {
    const days = dayjs.utc(day).diff(dayjs.utc(send.at.tz(timezone).format('YYYY-MM-DD')), 'day')
    if (days === 0 || !send.schedule) {
        return null
    }
    const at = shiftDays(send.at, days, send.schedule.timezone || 'UTC')
    return at.isAfter(now) ? { days, at } : null
}

/** The schedule fields that move every future send of a schedule by a number of days. */
export function movedScheduleFields(
    schedule: Pick<HogFlowScheduleApi, 'rrule' | 'starts_at' | 'timezone'>,
    days: number,
    now: dayjs.Dayjs = dayjs()
): { starts_at: string; rrule: string } {
    const timezone = schedule.timezone || 'UTC'
    const startsAt = dayjs(schedule.starts_at)
    if (isOneTimeSchedule(schedule.rrule)) {
        // A one-time rule can still name a weekday, which would move the send off the target day. Save the send
        // as a plain one-time rule at the time it actually goes out, shifted.
        const sendsAt = scheduleSendTimes(schedule, { start: startsAt, end: startsAt.add(1, 'year') })[0] ?? startsAt
        return { starts_at: shiftDays(sendsAt, days, timezone).toISOString(), rrule: ONE_TIME_RRULE }
    }
    // Start the shifted rule at the next send. Shifting the original start instead can bring a past send back
    // into the future, so the next send lands on the wrong day.
    const nextSend =
        scheduleSendTimes(schedule, { start: now, end: now.add(1, 'year') })[0] ?? dayjs(schedule.starts_at)
    const starts_at = shiftDays(nextSend, days, timezone).toISOString()
    const state = parseRRuleToState(schedule.rrule)
    const weekdays = state.weekdays.map((weekday) => (((weekday + days) % 7) + 7) % 7)
    // The shifted rule starts at the next send, so a series that ends after a count keeps only the sends left.
    const endCount =
        state.endType === 'after_count'
            ? Math.max(1, state.endCount - scheduleSendTimes(schedule, { start: startsAt, end: now }).length)
            : state.endCount
    // The end date moves with the sends, or the last send falls after it. stateToRRule reads the date in the
    // browser time zone, so pass a plain date, not the UTC instant from parseRRuleToState.
    const endDate = state.endDate ? dayjs.utc(state.endDate).add(days, 'day').format('YYYY-MM-DD') : null
    return { starts_at, rrule: stateToRRule({ ...state, weekdays, endCount, endDate }, starts_at) }
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

/** Splits a range into consecutive pieces of at most `maxDays`, for an endpoint that limits the range it takes. */
export function splitRange(range: CalendarRange, maxDays: number): CalendarRange[] {
    const pieces: CalendarRange[] = []
    let start = range.start
    while (start.isBefore(range.end)) {
        const end = start.add(maxDays, 'day').isBefore(range.end) ? start.add(maxDays, 'day') : range.end
        pieces.push({ start, end })
        start = end
    }
    return pieces
}

/** Joins the flows of several range loads. A flow shows up in each piece, with only the runs of that piece. */
export function mergeCalendarFlows(loads: SendCalendarFlowApi[][]): SendCalendarFlowApi[] {
    const byId = new Map<string, SendCalendarFlowApi>()
    for (const flow of loads.flat()) {
        const known = byId.get(flow.id)
        if (!known) {
            byId.set(flow.id, flow)
            continue
        }
        const runIds = new Set(known.batch_jobs.map((run) => run.id))
        byId.set(flow.id, {
            ...known,
            batch_jobs: [...known.batch_jobs, ...flow.batch_jobs.filter((run) => !runIds.has(run.id))],
        })
    }
    return [...byId.values()]
}
