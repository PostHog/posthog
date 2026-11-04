import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { chainToElements } from 'lib/utils/elements-chain'
import { autoCaptureEventToDescription } from 'lib/utils/events'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import type {
    TransactionalEmailLogEntryApi,
    TransactionalEmailLogEventApi,
} from 'products/messaging/frontend/generated/api.schemas'

/** How far before and after the send the page looks for what the person did. */
export const ACTIVITY_WINDOW_DAYS = 7
export const ACTIVITY_BEFORE_LIMIT = 50
export const ACTIVITY_AFTER_LIMIT = 100

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
}
export type ActivityOtherEmailRow = {
    kind: 'otherEmail'
    key: string
    at: string
    entry: TransactionalEmailLogEntryApi
}
export type ActivityEmailRow = { kind: 'email'; key: string; at: string; event: TransactionalEmailLogEventApi }
export type ActivityRow =
    | { kind: 'session'; key: string; sessionId: string; at: string }
    | ActivityEventRow
    | ActivityOtherEmailRow
    | { kind: 'emailGroup'; key: string; at: string; rows: ActivityEmailRow[] }

export interface ActivityTimeline {
    /** What the person did before the email went out. */
    before: ActivityRow[]
    /** The email's own steps, then what the person did after it went out. */
    after: ActivityRow[]
}

/**
 * The person's events, this email's steps and their other emails, in time order and split at the send. A row starts
 * each session, the email's consecutive steps fold into one block, and repeats of one interaction fold into one row.
 */
export function buildActivityTimeline(
    events: ActivityEvent[],
    emailEvents: TransactionalEmailLogEventApi[],
    otherEmails: TransactionalEmailLogEntryApi[],
    sentAt: string
): ActivityTimeline {
    const merged: (ActivityEventRow | ActivityEmailRow | ActivityOtherEmailRow)[] = [
        ...events.map(
            (event): ActivityEventRow => ({ kind: 'event', key: event.uuid, at: event.timestamp, event, count: 1 })
        ),
        ...otherEmails.map(
            (entry): ActivityOtherEmailRow => ({
                kind: 'otherEmail',
                key: entry.message_id,
                at: entry.created_at,
                entry,
            })
        ),
        ...emailEvents.map(
            (event, index): ActivityEmailRow => ({
                kind: 'email',
                key: `email-${event.kind}-${index}`,
                at: event.at,
                event,
            })
        ),
    ].sort((a, b) => dayjs(a.at).valueOf() - dayjs(b.at).valueOf())

    const sent = dayjs(sentAt)
    const isBefore = (row: ActivityEventRow | ActivityEmailRow | ActivityOtherEmailRow): boolean =>
        row.kind !== 'email' && dayjs(row.at).isBefore(sent)
    return {
        before: foldRows(merged.filter(isBefore)),
        after: foldRows(merged.filter((row) => !isBefore(row))),
    }
}

function foldRows(merged: (ActivityEventRow | ActivityEmailRow | ActivityOtherEmailRow)[]): ActivityRow[] {
    const rows: ActivityRow[] = []
    let currentSession: string | null = null
    for (const row of merged) {
        const last = rows[rows.length - 1]
        if (row.kind === 'email') {
            if (last?.kind === 'emailGroup') {
                last.rows.push(row)
            } else {
                rows.push({ kind: 'emailGroup', key: `group-${row.key}`, at: row.at, rows: [row] })
            }
            continue
        }
        if (row.kind === 'otherEmail') {
            rows.push(row)
            continue
        }
        if (
            last?.kind === 'event' &&
            last.event.event === row.event.event &&
            last.event.sessionId === row.event.sessionId &&
            describeActivityEvent(last.event) === describeActivityEvent(row.event)
        ) {
            last.count += 1
            continue
        }
        if (row.event.sessionId && row.event.sessionId !== currentSession) {
            currentSession = row.event.sessionId
            rows.push({ kind: 'session', key: `session-${row.key}`, sessionId: row.event.sessionId, at: row.at })
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

export interface ActivityAfterSummary {
    /** For example "Back in your app 3m after clicking", when the person returned after engaging with the email. */
    comeback: string | null
    eventCount: number
    sessionCount: number
    /** The custom events they did after the email, in the order they first did them. */
    outcomes: string[]
}

export function summarizeAfter(
    after: ActivityEvent[],
    timeline: readonly TransactionalEmailLogEventApi[]
): ActivityAfterSummary {
    const engagement = [...timeline].reverse().find((event) => event.kind === 'clicked' || event.kind === 'opened')
    const firstReturn = engagement ? after.find((event) => dayjs(event.timestamp).isAfter(engagement.at)) : undefined
    const comeback =
        engagement && firstReturn
            ? `Back in your app ${humanFriendlyDuration(
                  Math.max(1, dayjs(firstReturn.timestamp).diff(dayjs(engagement.at), 'second')),
                  { maxUnits: 1 }
              )} after ${engagement.kind === 'clicked' ? 'clicking the email' : 'opening the email'}`
            : null
    return {
        comeback,
        eventCount: after.length,
        sessionCount: new Set(after.map((event) => event.sessionId).filter(Boolean)).size,
        outcomes: Array.from(new Set(after.filter(isCustomEvent).map((event) => event.event))),
    }
}
