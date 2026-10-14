import type { DashboardBasicApi } from '@/api/dashboards'
import type { InsightBasicApi } from '@/api/insights'
import type { FileSystemShortcutApi } from '@/api/shortcuts'

import type { BrowseRow, DeviceRecentEntry, PinDisplay, PinView, RecentView, ViewKind } from '../views'

// Shortcut paths are escaped like the web's `escapePath` (`frontend/src/layout/panel-layout/ProjectTree/utils.tsx`):
// `\` becomes `\\` and `/` becomes `\/`, so a name with a slash stays one segment.

export function escapePath(segment: string): string {
    return segment.replace(/\\/g, '\\\\').replace(/\//g, '\\/')
}

/** The last segment of an escaped path, unescaped: the name the web shows for the shortcut. */
export function shortcutName(path: string): string {
    const segments: string[] = []
    let current = ''
    for (let index = 0; index < path.length; index += 1) {
        const char = path[index]
        if (char === '\\' && index + 1 < path.length) {
            current += path[index + 1]
            index += 1
        } else if (char === '/') {
            segments.push(current)
            current = ''
        } else {
            current += char
        }
    }
    segments.push(current)
    return segments.filter((segment) => segment.length > 0).pop() ?? ''
}

const NATIVE_KINDS: ReadonlySet<ViewKind> = new Set<ViewKind>(['dashboard', 'insight', 'web_analytics'])

export function viewKindForType(type: string | null): ViewKind {
    switch (type) {
        case 'dashboard':
        case 'insight':
        case 'web_analytics':
        case 'notebook':
        case 'canvas':
            return type
        default:
            return 'web_link'
    }
}

export function isNativeKind(kind: ViewKind): boolean {
    return NATIVE_KINDS.has(kind)
}

/**
 * The identity of a pinned view. Dashboards, insights and notebooks match by `type` and `ref`. A product page such as
 * web analytics has no `ref`, and the backend writes its stars without `href`, so it matches by `type` alone.
 */
export function shortcutMatchKey(type: string | null, ref: string | null): string {
    return ref ? `${type ?? ''}:${ref}` : `${type ?? ''}:`
}

export interface PinPrefs {
    rank: Record<string, number>
    display: Record<string, PinDisplay>
}

const ROW: PinDisplay = { mode: 'row' }

function keeps(a: FileSystemShortcutApi, b: FileSystemShortcutApi, rank: Record<string, number>): boolean {
    const aRanked = rank[a.id] !== undefined
    const bRanked = rank[b.id] !== undefined
    if (aRanked !== bRanked) {
        return aRanked
    }
    const aOrder = a.order ?? Number.POSITIVE_INFINITY
    const bOrder = b.order ?? Number.POSITIVE_INFINITY
    if (aOrder !== bOrder) {
        return aOrder < bOrder
    }
    return Date.parse(a.created_at) <= Date.parse(b.created_at)
}

/**
 * Pins from the server's shortcut rows, in this phone's order. Rows that match one view (a star in a sibling
 * environment, or one left over after a rename) collapse into one pin: the row with a local rank, else the lowest
 * `order`, then the oldest. Folder shortcuts are not views and are left out.
 */
export function pinsFromShortcuts(rows: readonly FileSystemShortcutApi[], prefs: PinPrefs): PinView[] {
    // Rows arrive in server order, so a group's first row holds its position.
    const groups = new Map<string, { kept: FileSystemShortcutApi; ids: string[]; serverOrder: number }>()
    rows.forEach((row, serverOrder) => {
        if (row.type === 'folder') {
            return
        }
        const key = shortcutMatchKey(row.type, row.ref)
        const group = groups.get(key)
        if (!group) {
            groups.set(key, { kept: row, ids: [row.id], serverOrder })
            return
        }
        group.ids.push(row.id)
        if (!keeps(group.kept, row, prefs.rank)) {
            group.kept = row
        }
    })
    const pins = [...groups.values()].map(({ kept, ids, serverOrder }): PinView => {
        const kind = viewKindForType(kept.type)
        return {
            kind,
            ref: kept.ref,
            href: kept.href,
            name: shortcutName(kept.path) || 'Untitled',
            shortcutId: kept.id,
            shortcutIds: ids,
            type: kept.type ?? '',
            serverOrder,
            rank: prefs.rank[kept.id] ?? null,
            display: isNativeKind(kind) ? (prefs.display[kept.id] ?? ROW) : ROW,
            native: isNativeKind(kind),
        }
    })
    return orderPins(pins)
}

/** Ranked pins by rank, then the pins without a rank (new on the web or on the phone) in server order. */
export function orderPins<T extends { rank: number | null; serverOrder: number }>(pins: readonly T[]): T[] {
    return [...pins].sort((a, b) => {
        if (a.rank !== null && b.rank !== null) {
            return a.rank - b.rank || a.serverOrder - b.serverOrder
        }
        if (a.rank !== null) {
            return -1
        }
        if (b.rank !== null) {
            return 1
        }
        return a.serverOrder - b.serverOrder
    })
}

export const RECENT_LIMIT = 10

function recentKey(kind: string, ref: string | null): string {
    return shortcutMatchKey(kind, ref)
}

/**
 * Recent: views opened on this phone and dashboards this user viewed on the web, newest first, one row per view,
 * without pinned views, at most 10. A web row with no `last_viewed_at` is a dashboard the user never viewed.
 */
export function mergeRecent(
    device: readonly DeviceRecentEntry[],
    serverDashboards: readonly DashboardBasicApi[],
    pinnedKeys: ReadonlySet<string>
): RecentView[] {
    const candidates: RecentView[] = [
        ...device.map(
            (entry): RecentView => ({
                kind: entry.kind,
                ref: entry.ref,
                href: hrefFor(entry.kind, entry.ref),
                name: entry.name,
                viewedAt: entry.viewedAt,
                source: 'device',
            })
        ),
        ...serverDashboards
            .filter((dashboard) => dashboard.last_viewed_at && !dashboard.deleted)
            .map(
                (dashboard): RecentView => ({
                    kind: 'dashboard',
                    ref: String(dashboard.id),
                    href: `/dashboard/${dashboard.id}`,
                    name: dashboard.name || 'Untitled',
                    viewedAt: dashboard.last_viewed_at as string,
                    source: 'server',
                })
            ),
    ]
    candidates.sort((a, b) => Date.parse(b.viewedAt) - Date.parse(a.viewedAt))
    const seen = new Set<string>()
    const merged: RecentView[] = []
    for (const view of candidates) {
        const key = recentKey(view.kind, view.ref)
        if (seen.has(key) || pinnedKeys.has(key)) {
            continue
        }
        seen.add(key)
        merged.push(view)
        if (merged.length === RECENT_LIMIT) {
            break
        }
    }
    return merged
}

function hrefFor(kind: ViewKind, ref: string | null): string | null {
    if (kind === 'dashboard' && ref) {
        return `/dashboard/${ref}`
    }
    if (kind === 'insight' && ref) {
        return `/insights/${ref}`
    }
    return kind === 'web_analytics' ? '/web' : null
}

/** Browse and search rows. Deleted dashboards are left out, as the web Views feed does. */
export function dashboardRows(rows: readonly DashboardBasicApi[]): BrowseRow[] {
    return rows
        .filter((row) => !row.deleted)
        .map((row) => ({
            kind: 'dashboard',
            ref: String(row.id),
            href: `/dashboard/${row.id}`,
            name: row.name || 'Untitled',
            description: row.description || null,
            at: row.last_viewed_at ?? null,
        }))
}

export function insightRows(rows: readonly InsightBasicApi[]): BrowseRow[] {
    return rows
        .filter((row) => !row.deleted)
        .map((row) => ({
            kind: 'insight',
            ref: row.short_id,
            href: `/insights/${row.short_id}`,
            name: row.name || row.derived_name || 'Untitled',
            description: row.description || null,
            at: row.last_modified_at ?? null,
        }))
}
