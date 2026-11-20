import { IconBuilding, IconPeople, IconPerson, IconSupport } from '@posthog/icons'

import { fileSystemBaseType } from 'scenes/analytics/analyticsUtils'
import { libraryObjectHref, libraryObjectName } from 'scenes/library/libraryUtils'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { TODAY_MONITOR_RECENT_TYPES } from '~/layout/today/todayMonitor'
import { newestByName } from '~/layout/today/todayNewestByName'
import { TODAY_PEOPLE_RECENT_TYPES } from '~/layout/today/todayPeople'
import type { StoredReleaseRecent } from '~/layout/today/todayRecents'
import { TodayRailPane } from '~/layout/today/todayShellLogic'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import type { TodayRailPreviewItem } from './TodayRailPreviewList'

export const RAIL_RECENTS_LIMIT = 3

const PEOPLE_ICONS: Record<string, JSX.Element> = {
    person: <IconPerson />,
    group: <IconBuilding />,
    account: <IconBuilding />,
    cohort: <IconPeople />,
    ticket: <IconSupport />,
}

const PANE_TYPES: Partial<Record<TodayRailPane, readonly string[]>> = {
    people: TODAY_PEOPLE_RECENT_TYPES,
    monitor: TODAY_MONITOR_RECENT_TYPES,
    release: ['feature_flag', 'experiment', 'early_access_feature', 'release'],
}

export function railEntryMatchesPane(entry: FileSystemEntry, pane: TodayRailPane): boolean {
    const type = fileSystemBaseType(entry.type)
    return pane === 'products' ? !['folder', 'task'].includes(type) : (PANE_TYPES[pane]?.includes(type) ?? false)
}

export function railPreviewItem(entry: FileSystemEntry): TodayRailPreviewItem | null {
    const href = libraryObjectHref(entry)
    if (!href) {
        return null
    }
    return {
        name: libraryObjectName(entry),
        href,
        icon: PEOPLE_ICONS[entry.type ?? ''] ?? iconForType(entry.type as FileSystemIconType),
    }
}

export function railPreviewItems(entries: FileSystemEntry[], pane: TodayRailPane): TodayRailPreviewItem[] {
    return [
        ...new Map(
            entries
                .filter((entry) => railEntryMatchesPane(entry, pane))
                .flatMap((entry) => {
                    const item = railPreviewItem(entry)
                    return item ? [[item.href, item] as const] : []
                })
        ).values(),
    ]
}

export function railRecentItems(items: TodayRailPreviewItem[], pins: TodayRailPreviewItem[]): TodayRailPreviewItem[] {
    const pinnedHrefs = new Set(pins.map((item) => item.href))
    const unique = [...new Map(items.map((item) => [item.href, item])).values()]
    return newestByName(
        unique.filter((item) => !pinnedHrefs.has(item.href)),
        (item) => item.name,
        (item) => item.href,
        RAIL_RECENTS_LIMIT
    )
}

export function localRecentEntry(recent: { type: string; name: string; href: string }): FileSystemEntry {
    return { id: recent.href, path: escapePath(recent.name), type: recent.type, href: recent.href }
}

export function namedReleaseEntries(
    entries: FileSystemEntry[],
    releaseRecents: StoredReleaseRecent[]
): FileSystemEntry[] {
    const names = new Map(releaseRecents.map((recent) => [recent.id, recent.name]))
    return entries.flatMap((entry) => {
        if (entry.type !== 'release') {
            return [entry]
        }
        const name = names.get(entry.ref ?? '')
        return name ? [{ ...entry, path: escapePath(name) }] : []
    })
}

export function releaseRecentEntries(
    recents: FileSystemEntry[],
    releaseRecents: StoredReleaseRecent[]
): FileSystemEntry[] {
    const visits = releaseRecents.map((recent) => ({
        ...localRecentEntry(recent),
        ref: recent.id,
        last_viewed_at: new Date(recent.viewedAt).toISOString(),
    }))
    return [
        ...namedReleaseEntries(
            recents.filter((entry) => !!entry.ref),
            releaseRecents
        ),
        ...visits,
    ].sort(
        (first, second) =>
            (Date.parse(second.last_viewed_at ?? '') || 0) - (Date.parse(first.last_viewed_at ?? '') || 0)
    )
}
