import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { ActivityEventRow, ActivityRow } from './emailActivity'

/** A row with no session of its own, such as a server-side event, stays in a session it happened this close to. */
const SESSION_JOIN_MINUTES = 30

export interface ActivityGroup {
    key: string
    /** Null for rows outside any session, which have no replay. */
    sessionId: string | null
    rows: ActivityRow[]
    startAt: string
    endAt: string
    eventCount: number
}

function toGroup(sessionId: string | null, rows: ActivityRow[]): ActivityGroup {
    const events = rows.filter((row): row is ActivityEventRow => row.kind === 'event')
    return {
        key: `${sessionId ?? 'no-session'}-${rows[0].key}`,
        sessionId,
        rows,
        startAt: rows[0].at,
        endAt: rows[rows.length - 1].at,
        eventCount: events.reduce((total, row) => total + row.count, 0),
    }
}

/** Splits timeline rows at each session, so a session and its replay read as one thing. */
export function groupActivityRows(rows: ActivityRow[]): ActivityGroup[] {
    const groups: ActivityGroup[] = []
    let sessionId: string | null = null
    let current: ActivityRow[] = []
    const flush = (): void => {
        if (current.length) {
            groups.push(toGroup(sessionId, current))
        }
        current = []
    }
    for (const row of rows) {
        const rowSession = row.kind === 'event' ? row.event.sessionId : null
        const last = current[current.length - 1]
        const closeToLast = !!last && dayjs(row.at).diff(dayjs(last.at), 'minute') < SESSION_JOIN_MINUTES
        if (rowSession ? rowSession !== sessionId : !!sessionId && !closeToLast) {
            flush()
            sessionId = rowSession
        }
        current.push(row)
    }
    flush()
    return groups
}

/** "21s", the time between a group's first and last row. */
export function groupDuration(group: ActivityGroup): string {
    return humanFriendlyDuration(Math.max(1, dayjs(group.endAt).diff(dayjs(group.startAt), 'second')), { maxUnits: 2 })
}

/** "8h later", when a noticeable stretch of time separates two groups. */
export function gapBetween(fromAt: string, toAt: string): string | null {
    const seconds = dayjs(toAt).diff(dayjs(fromAt), 'second')
    return seconds >= 60 ? `${humanFriendlyDuration(seconds, { maxUnits: 1 })} later` : null
}
