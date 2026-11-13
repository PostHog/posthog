import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { pinKey } from '~/layout/today/sidebar/sidebarPinsLogic'
import { TODAY_MONITOR_RECENT_TYPES, TodayMonitorRecent, TodayMonitorRecentType } from '~/layout/today/todayMonitor'
import { FileSystemEntry } from '~/queries/schema/schema-general'

export interface TodayMonitorPin extends TodayMonitorRecent {
    key: string
}

function isMonitorRecentType(type: string | undefined): type is TodayMonitorRecentType {
    return (TODAY_MONITOR_RECENT_TYPES as readonly (string | undefined)[]).includes(type)
}

/** Issues and saved log views have no file system row, so they pin by href. */
export function monitorPinsFromShortcuts(shortcuts: FileSystemEntry[]): TodayMonitorPin[] {
    const pins = new Map<string, TodayMonitorPin>()
    for (const shortcut of shortcuts) {
        if (!shortcut.href || !isMonitorRecentType(shortcut.type)) {
            continue
        }
        const key = pinKey(shortcut.type, shortcut.href)
        if (!pins.has(key)) {
            pins.set(key, {
                key,
                type: shortcut.type,
                name: splitPath(shortcut.path).at(-1) ?? shortcut.path,
                href: shortcut.href,
            })
        }
    }
    return [...pins.values()]
}
