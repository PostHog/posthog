import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { ACTIVITY_JOIN_MINUTES, ActivityEventRow, ActivityRow, isCustomEvent } from './emailActivity'

export interface ActivityGroup {
    key: string
    /** Null for rows outside any session, which have no replay. */
    sessionId: string | null
    rows: ActivityRow[]
    startAt: string
    endAt: string
    eventCount: number
}

function lastRowAt(row: ActivityRow): string {
    return row.kind === 'event' ? row.lastAt : row.at
}

function toGroup(sessionId: string | null, rows: ActivityRow[]): ActivityGroup {
    const events = rows.filter((row): row is ActivityEventRow => row.kind === 'event')
    return {
        key: `${sessionId ?? 'no-session'}-${rows[0].key}`,
        sessionId,
        rows,
        startAt: rows[0].at,
        endAt: lastRowAt(rows[rows.length - 1]),
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
        const closeToLast = !!last && dayjs(row.at).diff(dayjs(lastRowAt(last)), 'minute') < ACTIVITY_JOIN_MINUTES
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

/** The most rows a group shows until the reader opens it. */
const COLLAPSED_GROUP_ROWS = 4

export interface CollapsedGroup {
    rows: ActivityRow[]
    /** How many more rows the group shows when it opens. */
    hidden: number
}

/** What a long group shows at first: its custom events and emails once each, or else its first rows. */
export function collapseGroup(group: ActivityGroup): CollapsedGroup {
    if (group.rows.length <= COLLAPSED_GROUP_ROWS) {
        return { rows: group.rows, hidden: 0 }
    }
    const byName = new Map<string, ActivityRow>()
    for (const row of group.rows) {
        if (row.kind === 'otherEmail') {
            byName.set(row.key, row)
        } else if (isCustomEvent(row.event)) {
            const seen = byName.get(row.event.event)
            byName.set(
                row.event.event,
                seen?.kind === 'event' ? { ...seen, count: seen.count + row.count, lastAt: row.lastAt } : row
            )
        }
    }
    const important = Array.from(byName.values())
    const rows = (important.length ? important : group.rows).slice(0, COLLAPSED_GROUP_ROWS)
    return { rows, hidden: group.rows.length - rows.length }
}
