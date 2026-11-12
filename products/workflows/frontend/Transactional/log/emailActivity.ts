import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { chainToElements } from 'lib/utils/elements-chain'
import { autoCaptureEventToDescription } from 'lib/utils/events'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type {
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEntryApi,
    TransactionalEmailLogEventApi,
} from 'products/messaging/frontend/generated/api.schemas'

/** How far before and after the send the page looks for what the person did. */
export const ACTIVITY_WINDOW_DAYS = 7
/** A row with no session of its own stays with activity it happened this close to. */
export const ACTIVITY_JOIN_MINUTES = 30

export interface ActivityEvent {
    uuid: string
    event: string
    timestamp: string
    url: string | null
    pathname: string | null
    sessionId: string | null
    eventType: string | null
    elementsChain: string
}

export interface ActivityPerson {
    id: string
    properties: Record<string, any>
    createdAt: string
}

export interface PersonActivity {
    before: ActivityEvent[]
    after: ActivityEvent[]
    /** True when the window held more events before the send than the page loaded. */
    hasMoreBefore: boolean
    hasMoreAfter: boolean
}

/** A short sentence for what the person did, such as "Viewed /pricing". */
export function describeActivityEvent(event: ActivityEvent): string {
    if (event.event === '$pageview' || event.event === '$screen') {
        const path = event.pathname || (event.url ? safePathname(event.url) : null)
        return path ? `Viewed ${path}` : 'Viewed a page'
    }
    if (event.event === '$autocapture') {
        return capitalizeFirstLetter(
            autoCaptureEventToDescription({
                event: event.event,
                properties: { $event_type: event.eventType },
                elements: chainToElements(event.elementsChain),
            })
        )
    }
    if (event.event === '$rageclick') {
        return 'Rage clicked'
    }
    return event.event
}

/** Custom events are what the product chose to track, so they read as outcomes. */
export function isCustomEvent(event: ActivityEvent): boolean {
    return !event.event.startsWith('$')
}

function safePathname(url: string): string | null {
    try {
        return new URL(url).pathname
    } catch {
        return null
    }
}

export type ActivityEventRow = {
    kind: 'event'
    key: string
    at: string
    event: ActivityEvent
    /** How many identical events in a row this one stands for. */
    count: number
    /** When the last of those identical events happened. */
    lastAt: string
}
export type ActivityOtherEmailRow = {
    kind: 'otherEmail'
    key: string
    at: string
    entry: TransactionalEmailLogEntryApi
}
export type ActivityRow = ActivityEventRow | ActivityOtherEmailRow

export interface ActivityTimeline {
    /** What the person did before the email went out. */
    before: ActivityRow[]
    /** What the person did after the email went out. */
    after: ActivityRow[]
}

/** The person's events and other emails, in time order and split at the send. Repeats of one interaction fold into one row. */
export function buildActivityTimeline(
    events: ActivityEvent[],
    otherEmails: TransactionalEmailLogEntryApi[],
    sentAt: string
): ActivityTimeline {
    const merged: ActivityRow[] = [
        ...events.map(
            (event): ActivityEventRow => ({
                kind: 'event',
                key: event.uuid,
                at: event.timestamp,
                lastAt: event.timestamp,
                event,
                count: 1,
            })
        ),
        ...otherEmails.map(
            (entry): ActivityOtherEmailRow => ({
                kind: 'otherEmail',
                key: entry.message_id,
                at: entry.created_at,
                entry,
            })
        ),
    ].sort((a, b) => dayjs(a.at).valueOf() - dayjs(b.at).valueOf())

    const sent = dayjs(sentAt)
    const isBefore = (row: ActivityRow): boolean => dayjs(row.at).isBefore(sent)
    return {
        before: foldRows(merged.filter(isBefore)),
        after: foldRows(merged.filter((row) => !isBefore(row))),
    }
}

function foldRows(merged: ActivityRow[]): ActivityRow[] {
    const rows: ActivityRow[] = []
    for (const row of merged) {
        const last = rows[rows.length - 1]
        if (
            row.kind === 'event' &&
            last?.kind === 'event' &&
            last.event.event === row.event.event &&
            last.event.sessionId === row.event.sessionId &&
            (!!row.event.sessionId || dayjs(row.at).diff(dayjs(last.lastAt), 'minute') < ACTIVITY_JOIN_MINUTES) &&
            describeActivityEvent(last.event) === describeActivityEvent(row.event)
        ) {
            last.count += 1
            last.lastAt = row.at
            continue
        }
        rows.push(row)
    }
    return rows
}

/** "2m before", "at send" or "3h after", measured from when the email went out. */
export function relativeToSend(at: string, sentAt: string): string {
    const seconds = dayjs(at).diff(dayjs(sentAt), 'second')
    if (Math.abs(seconds) < 1) {
        return 'at send'
    }
    const duration = humanFriendlyDuration(Math.abs(seconds), { maxUnits: 1 })
    return seconds < 0 ? `${duration} before` : `${duration} after`
}

/** When the email went out, which is the line between what the person did before and after it. */
export function emailSentAt(email: Pick<TransactionalEmailLogDetailApi, 'timeline' | 'created_at'>): string {
    return email.timeline.find((event) => event.kind === 'sent')?.at ?? email.created_at
}

/** A server-side event has no session or page, so it does not show that the person came back. */
function isPersonInApp(event: ActivityEvent): boolean {
    return !!event.sessionId || event.event === '$pageview' || event.event === '$screen'
}

/** The person may have had the app open all along when they opened the email, so only a fresh start counts as coming back. */
function cameBack(event: ActivityEvent, earlier: ActivityEvent[]): boolean {
    if (event.sessionId) {
        return !earlier.some((other) => other.sessionId === event.sessionId)
    }
    return !earlier.some(
        (other) =>
            isPersonInApp(other) &&
            dayjs(event.timestamp).diff(dayjs(other.timestamp), 'minute') < ACTIVITY_JOIN_MINUTES
    )
}

function firstReturnToApp(
    activity: Pick<PersonActivity, 'before' | 'after'>,
    timeline: readonly TransactionalEmailLogEventApi[]
): { event: ActivityEvent; engagement: TransactionalEmailLogEventApi } | null {
    const engagements = timeline.filter((event) => event.kind === 'clicked' || event.kind === 'opened').reverse()
    const loaded = [...activity.before, ...activity.after]
    for (const event of activity.after.filter(isPersonInApp)) {
        const earlierEngagements = engagements.filter((candidate) => dayjs(event.timestamp).isAfter(candidate.at))
        const click = earlierEngagements.find((candidate) => candidate.kind === 'clicked')
        if (click) {
            return { event, engagement: click }
        }
        const earlier = loaded.filter((other) => dayjs(other.timestamp).isBefore(event.timestamp))
        if (earlierEngagements.length && cameBack(event, earlier)) {
            return { event, engagement: earlierEngagements[0] }
        }
    }
    return null
}

/** For example "Back in your app 3m after clicking the email", when the person returned after engaging with it. */
export function describeComeback(
    activity: Pick<PersonActivity, 'before' | 'after'>,
    timeline: readonly TransactionalEmailLogEventApi[]
): string | null {
    const firstReturn = firstReturnToApp(activity, timeline)
    if (!firstReturn) {
        return null
    }
    const backAfter = humanFriendlyDuration(
        Math.max(1, dayjs(firstReturn.event.timestamp).diff(dayjs(firstReturn.engagement.at), 'second')),
        { maxUnits: 1 }
    )
    return `Back in your app ${backAfter} after ${firstReturn.engagement.kind === 'clicked' ? 'clicking' : 'opening'} the email`
}
