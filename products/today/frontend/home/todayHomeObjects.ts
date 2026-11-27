import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { pinKey } from '~/layout/today/sidebar/sidebarPinsLogic'
import { StoredAutomateRecent } from '~/layout/today/todayAutomateRecents'
import { TodayRecordType, todayRecordType } from '~/layout/today/todayRecordTypes'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { localRecentEntry, railEntryMatchesPane, railPreviewItem } from '../rail/todayRailPreviewItems'

export const HOME_LIST_PAGE_SIZE = 5

export interface HomeObjectRow {
    key: string
    type: string
    ref?: string
    name: string
    href: string
    icon: JSX.Element
    typeCopy: TodayRecordType
}

/**
 * Every record the Products pane would list, once each, in the order given. Home lists the whole project, so only
 * folders and tasks drop out, as they do in the Products pane.
 */
export function homeObjectRows(entries: FileSystemEntry[]): HomeObjectRow[] {
    const rows = new Map<string, HomeObjectRow>()
    for (const entry of entries) {
        const type = entry.type ?? ''
        const item = railEntryMatchesPane(entry, 'products') ? railPreviewItem(entry) : null
        if (item && !rows.has(item.href)) {
            const typeCopy = todayRecordType(type)
            rows.set(item.href, {
                key: pinKey(type, item.href),
                type,
                ref: entry.ref ?? undefined,
                name: item.name,
                href: item.href,
                // The icon a pane gives the type, so a record looks the same in Home as in its pane.
                icon: typeCopy.iconType ? iconForType(typeCopy.iconType) : item.icon,
                typeCopy,
            })
        }
    }
    return [...rows.values()]
}

function viewedAt(entry: Pick<FileSystemEntry, 'last_viewed_at'>): number {
    return Date.parse(entry.last_viewed_at ?? '') || 0
}

/**
 * The server's recents with the Automate recents it keeps no views for, newest first. Workflows, broadcasts,
 * subscriptions and scouts have no file system rows, so only the browser knows they were opened. The server lists
 * destinations itself.
 */
export function homeRecentEntries(
    serverEntries: FileSystemEntry[],
    serverHasMore: boolean,
    automateRecents: StoredAutomateRecent[]
): FileSystemEntry[] {
    // The server sends its newest views only. A recent older than all of them can be behind views it did not send.
    const oldestServerView = serverHasMore ? Math.min(...serverEntries.map(viewedAt)) : 0
    const localEntries = automateRecents
        .filter((recent) => recent.type !== 'hog_function/destination')
        .map(
            (recent): FileSystemEntry => ({
                ...localRecentEntry(recent),
                last_viewed_at: recent.viewedAt ? new Date(recent.viewedAt).toISOString() : null,
            })
        )
        .filter((entry) => viewedAt(entry) >= oldestServerView)
    return [...serverEntries, ...localEntries].sort((a, b) => viewedAt(b) - viewedAt(a))
}
