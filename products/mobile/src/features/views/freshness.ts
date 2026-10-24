import { serverNow, serverOffsetMs } from '@/api/serverClock'
import type { Freshness } from '@/model/views'

import type { BlockedReason } from './analytics'

/** An automatic read checks an item again at least this often. */
export const RECHECK_MS = 5 * 60_000
/** At most one request per item in this time. */
export const READ_FLOOR_MS = 60_000
/** The server's `Date` header has 1 s resolution and latency adds more, so a force waits this long past the window. */
export const FORCE_MARGIN_MS = 2_000
/** One pull pass per list or dashboard in this time, like the web dashboard's refresh button. */
export const BULK_FLOOR_MS = 5 * 60_000
export const HINT_MS = 3_000
/** Keep tap and pull feedback visible even when a refresh sends nothing or finishes immediately. */
export const REFRESH_MIN_MS = 400

export function hasGoodValue(snapshot: Freshness | undefined): boolean {
    return Boolean(snapshot?.lastRefreshAt)
}

/**
 * Device ms at which an automatic, non-forced read is due: when there is no good value, when `cache_target_age` has
 * passed, or 5 minutes after the last read, and never within 60 s of the last read. Never read: due now.
 */
export function dueAt(snapshot: Freshness | undefined, offsetMs: number = serverOffsetMs()): number {
    if (!snapshot) {
        return 0
    }
    const { readAt } = snapshot
    const targetAt =
        snapshot.lastRefreshAt && snapshot.cacheTargetAge ? Date.parse(snapshot.cacheTargetAge) - offsetMs : readAt
    return Math.max(readAt + READ_FLOOR_MS, Math.min(readAt + RECHECK_MS, targetAt))
}

export function isDue(snapshot: Freshness | undefined, now: number = Date.now()): boolean {
    return now >= dueAt(snapshot)
}

/** For a TanStack `staleTime` function: stale exactly when the item is due. */
export function staleTimeFor(snapshot: Freshness | undefined, dataUpdatedAt: number): number {
    return Math.max(0, dueAt(snapshot) - dataUpdatedAt)
}

/** The server would compute on a `blocking` read: no `cache_target_age`, or it has passed. The web's tile rule. */
export function cacheTargetPassed(snapshot: Freshness | undefined, now: number = serverNow()): boolean {
    return !snapshot?.cacheTargetAge || Date.parse(snapshot.cacheTargetAge) <= now
}

/**
 * Server ms from which a tap may force this item: past `next_allowed_client_refresh`, and a minute after its last read,
 * because the queue sends at most one request per item per minute. Null for an item with no good value, which never
 * forces.
 */
export function forceAllowedAt(snapshot: Freshness | undefined, offsetMs: number = serverOffsetMs()): number | null {
    if (!hasGoodValue(snapshot) || !snapshot?.nextAllowedRefreshAt) {
        return null
    }
    return Math.max(
        Date.parse(snapshot.nextAllowedRefreshAt) + FORCE_MARGIN_MS,
        snapshot.readAt + offsetMs + READ_FLOOR_MS
    )
}

/** True when a tap may force this item: it has a good value, its window has passed, and its last read is a minute old. */
export function isEligible(snapshot: Freshness | undefined, now: number = serverNow()): boolean {
    const allowedAt = forceAllowedAt(snapshot)
    return allowedAt !== null && now >= allowedAt
}

/** True when the last read of the item is at least `READ_FLOOR_MS` old, so a cache-only re-read may go out. */
export function readFloorPassed(readAt: number | null | undefined, now: number = Date.now()): boolean {
    return !readAt || now - readAt >= READ_FLOOR_MS
}

/**
 * True when a pull may re-read one item from the cache. On a screen with a bulk floor, which is the list,
 * each item re-reads at most once per 5 minutes. Otherwise a pull every minute re-reads every pin each minute and
 * empties the insights bucket within the hour, which stops every insight read in the app. A single view re-reads after
 * a minute.
 */
export function cacheReadAllowed(
    readAt: number | null | undefined,
    bulkFloor: boolean,
    now: number = Date.now()
): boolean {
    return !readAt || now - readAt >= (bulkFloor ? RECHECK_MS : READ_FLOOR_MS)
}

export type StatusLine =
    | { kind: 'hidden'; text: null }
    | { kind: 'updating'; text: string }
    | { kind: 'fresh'; text: string }
    | { kind: 'age'; text: string; failed: boolean }

function ageText(ageMs: number): string {
    const minutes = Math.max(1, Math.floor(ageMs / 60_000))
    if (minutes < 60) {
        return `${minutes} min ago`
    }
    const hours = Math.floor(minutes / 60)
    if (hours < 24) {
        return `${hours} h ago`
    }
    const days = Math.floor(hours / 24)
    return days === 1 ? '1 day ago' : `${days} days ago`
}

/**
 * The status line under a screen title, from the visible items:
 * - "Updating…" only while a request of the screen runs;
 * - "Updated N min ago" from the oldest good `last_refresh`, which is honest for every number on screen;
 * - "Updated just now" only when that oldest value is under a minute old, which means every visible item refreshed;
 * - "Couldn't refresh. Updated 3 h ago" when a visible item's last read failed;
 * - hidden when no visible item shows data, such as a list of Row pins.
 */
export function statusLine(
    snapshots: readonly (Freshness | undefined)[],
    busy: boolean,
    now: number = serverNow()
): StatusLine {
    if (busy) {
        return { kind: 'updating', text: 'Updating…' }
    }
    const refreshed = snapshots.flatMap((snapshot) =>
        snapshot?.lastRefreshAt ? [Date.parse(snapshot.lastRefreshAt)] : []
    )
    if (refreshed.length === 0) {
        return { kind: 'hidden', text: null }
    }
    const age = Math.max(0, now - Math.min(...refreshed))
    const failed = snapshots.some((snapshot) => snapshot?.refreshFailed)
    if (failed) {
        return { kind: 'age', text: `Couldn't refresh. Updated ${ageText(age)}`, failed: true }
    }
    if (age < 60_000) {
        return { kind: 'fresh', text: 'Updated just now' }
    }
    return { kind: 'age', text: `Updated ${ageText(age)}`, failed: false }
}

export interface BlockedState {
    /** Nothing may be forced: a pull only shows the hint and re-reads from the cache. */
    blocked: boolean
    /** Server ms when a force is allowed again. */
    until: number | null
    reason: BlockedReason | null
}

export const NOT_BLOCKED: BlockedState = { blocked: false, until: null, reason: null }

export interface BlockedInput {
    /** The visible data items. */
    snapshots: readonly (Freshness | undefined)[]
    /** Server ms when this screen's bulk floor ends. */
    bulkFloorUntil: number | null
    /** Server ms when the dashboard's shared floor ends. */
    dashboardFloorUntil?: number | null
    now?: number
}

/**
 * "Nothing may be forced": a bulk floor is active, or every visible item has a good value and none is past its
 * window. An item without a good value never blocks, because a pull reads it with `blocking`. A screen with no data
 * items is never blocked; its pull re-reads the lists.
 */
export function blockedState(input: BlockedInput): BlockedState {
    const now = input.now ?? serverNow()
    const floor = input.bulkFloorUntil && input.bulkFloorUntil > now ? input.bulkFloorUntil : null
    const dashboardFloor =
        input.dashboardFloorUntil && input.dashboardFloorUntil > now ? input.dashboardFloorUntil : null
    const { snapshots } = input
    const windowBlocked =
        snapshots.length > 0 &&
        snapshots.every(hasGoodValue) &&
        !snapshots.some((snapshot) => isEligible(snapshot, now))
    if (!floor && !dashboardFloor && !windowBlocked) {
        return NOT_BLOCKED
    }
    const allowedTimes = snapshots.flatMap((snapshot) => {
        const allowedAt = forceAllowedAt(snapshot)
        return allowedAt === null ? [] : [allowedAt]
    })
    const earliestItem = allowedTimes.length > 0 ? Math.min(...allowedTimes) : null
    const until = Math.max(floor ?? 0, dashboardFloor ?? 0, windowBlocked ? (earliestItem ?? 0) : 0)
    const reason: BlockedReason = floor ? 'bulk_floor' : dashboardFloor ? 'dashboard_floor' : 'item_window'
    return { blocked: true, until: until > 0 ? until : null, reason }
}

/** Whole minutes from now until `until`, rounded up, at least 1. */
export function minutesUntil(until: number | null, now: number = serverNow()): number {
    if (until === null) {
        return 1
    }
    return Math.max(1, Math.ceil((until - now) / 60_000))
}

export function refreshHintText(until: number | null, now: number = serverNow()): string {
    return `You can refresh again in ${minutesUntil(until, now)} min.`
}

/**
 * The web dashboard's shared rule: a forced pass waits until `Dashboard.last_refresh` is 5 minutes old, unless the
 * oldest visible tile is already 5 minutes old. Returns the server ms when the rule stops blocking, or null.
 */
export function dashboardFloorUntil(
    dashboardLastRefresh: string | null,
    tiles: readonly (Freshness | undefined)[],
    now: number = serverNow()
): number | null {
    if (!dashboardLastRefresh) {
        return null
    }
    const end = Date.parse(dashboardLastRefresh) + BULK_FLOOR_MS
    if (Number.isNaN(end) || end <= now) {
        return null
    }
    const refreshed = tiles.flatMap((tile) => (tile?.lastRefreshAt ? [Date.parse(tile.lastRefreshAt)] : []))
    if (refreshed.length > 0 && now - Math.min(...refreshed) >= BULK_FLOOR_MS) {
        return null
    }
    return end
}

// One bulk floor per screen (`list`, `dashboard:{id}`), in memory, so it survives leaving and reopening the screen.
const bulkFloors = new Map<string, number>()

export function bulkFloorUntil(screenKey: string): number | null {
    return bulkFloors.get(screenKey) ?? null
}

export function startBulkFloor(screenKey: string, now: number = serverNow()): void {
    bulkFloors.set(screenKey, now + BULK_FLOOR_MS)
}

export function clearBulkFloors(): void {
    bulkFloors.clear()
}
