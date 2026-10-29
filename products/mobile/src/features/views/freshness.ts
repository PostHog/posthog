import { serverNow, serverOffsetMs } from '@/api/serverClock'
import type { Freshness } from '@/model/views'

import type { BlockedReason } from './analytics'

/** An automatic read checks an item again at least this often. */
export const RECHECK_MS = 5 * 60_000
export const READ_FLOOR_MS = 60_000
/** The server's `Date` header has 1 s resolution and latency adds more, so a force waits this long past the window. */
export const FORCE_MARGIN_MS = 2_000
export const BULK_FLOOR_MS = 5 * 60_000
export const HINT_MS = 3_000
/** Manual refresh shows its spinner at least this long, including a fast cache read. */
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
 * Server ms from which a tap may force this item: past `next_allowed_client_refresh`. Reading a cached value does not
 * delay a manual refresh. Null for an item with no good value or no known refresh window, which never forces.
 */
export function forceAllowedAt(snapshot: Freshness | undefined): number | null {
    if (!hasGoodValue(snapshot) || !snapshot?.nextAllowedRefreshAt) {
        return null
    }
    const allowedAt = Date.parse(snapshot.nextAllowedRefreshAt) + FORCE_MARGIN_MS
    return Number.isFinite(allowedAt) ? allowedAt : null
}

export function isEligible(snapshot: Freshness | undefined, now: number = serverNow()): boolean {
    const allowedAt = forceAllowedAt(snapshot)
    return allowedAt !== null && now >= allowedAt
}

/** True when the last read of the item is at least `READ_FLOOR_MS` old, so a cache-only re-read may go out. */
export function readFloorPassed(readAt: number | null | undefined, now: number = Date.now()): boolean {
    return !readAt || now - readAt >= READ_FLOOR_MS
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
    /** Nothing may be forced; manual refresh can still read the latest cached results. */
    blocked: boolean
    /** Server ms when a force is allowed again. */
    until: number | null
    reason: BlockedReason | null
}

export const NOT_BLOCKED: BlockedState = { blocked: false, until: null, reason: null }

export interface BlockedInput {
    /** The visible data items. */
    snapshots: readonly (Freshness | undefined)[]
    /** Server ms when the dashboard's shared floor ends. */
    dashboardFloorUntil?: number | null
    now?: number
}

export function blockedState(input: BlockedInput): BlockedState {
    const now = input.now ?? serverNow()
    const dashboardFloor =
        input.dashboardFloorUntil && input.dashboardFloorUntil > now ? input.dashboardFloorUntil : null
    const { snapshots } = input
    const windowBlocked =
        snapshots.length > 0 &&
        snapshots.every(hasGoodValue) &&
        !snapshots.some((snapshot) => isEligible(snapshot, now))
    if (!dashboardFloor && !windowBlocked) {
        return NOT_BLOCKED
    }
    const allowedTimes = snapshots.flatMap((snapshot) => {
        const allowedAt = forceAllowedAt(snapshot)
        return allowedAt === null ? [] : [allowedAt]
    })
    const earliestItem = allowedTimes.length > 0 ? Math.min(...allowedTimes) : null
    const until = Math.max(dashboardFloor ?? 0, windowBlocked ? (earliestItem ?? 0) : 0)
    const reason: BlockedReason = dashboardFloor ? 'dashboard_floor' : 'item_window'
    return { blocked: true, until: until > 0 ? until : null, reason }
}

/** Whole minutes from now until `until`, rounded up, at least 1. */
export function minutesUntil(until: number, now: number = serverNow()): number {
    return Math.max(1, Math.ceil((until - now) / 60_000))
}

export function refreshHintText(until: number | null, now: number = serverNow()): string {
    if (until === null || !Number.isFinite(until) || until <= now) {
        return 'Showing the latest available data.'
    }
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
