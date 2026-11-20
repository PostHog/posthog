import { useValues } from 'kea'

import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { TODAY_PANES } from '~/layout/today/todayRailItems'
import { todayRecentsLogic } from '~/layout/today/todayRecentsLogic'
import { TodayRailPane } from '~/layout/today/todayShellLogic'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { railPreviewItems, railRecentItems } from './todayRailPreviewItems'
import { TodayRailPreviewList } from './TodayRailPreviewList'

export function TodayRailHoverCard({ pane, onAction }: { pane: TodayRailPane; onAction: () => void }): JSX.Element {
    const { shortcutData, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { recents, recentsLoading } = useValues(recentItemsModel)
    const { peopleRecents, monitorRecents, releaseRecents } = useValues(todayRecentsLogic)
    const localRecents: FileSystemEntry[] = [...peopleRecents, ...monitorRecents, ...releaseRecents].map((recent) => ({
        id: recent.href,
        path: escapePath(recent.name),
        type: recent.type,
        href: recent.href,
    }))
    const pins = railPreviewItems(shortcutData, pane)
    const recentRows = railRecentItems(railPreviewItems([...recents, ...localRecents], pane), pins)
    const hasItems = pane !== 'settings'

    return (
        <TodayRailPreviewList
            title={TODAY_PANES[pane].label}
            pins={pins}
            recents={recentRows}
            loading={hasItems && (shortcutDataLoading || recentsLoading)}
            onAction={onAction}
        />
    )
}
