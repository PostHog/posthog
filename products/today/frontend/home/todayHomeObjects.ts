import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { pinKey } from '~/layout/today/sidebar/sidebarPinsLogic'
import { TodayRecordType, todayRecordType } from '~/layout/today/todayRecordTypes'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { railEntryMatchesPane, railPreviewItem } from '../rail/todayRailPreviewItems'

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
