import { useValues } from 'kea'

import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { TODAY_PANES } from '~/layout/today/todayRailItems'
import { todayRecentsLogic } from '~/layout/today/todayRecentsLogic'
import { TodayRailPane } from '~/layout/today/todayShellLogic'
import { recentItemsModel } from '~/models/recentItemsModel'

import {
    localRecentEntry,
    namedReleaseEntries,
    railPreviewItems,
    railRecentItems,
    releaseRecentEntries,
} from './todayRailPreviewItems'
import { TodayRailPreviewList } from './TodayRailPreviewList'

export function TodayRailHoverCard({ pane, onAction }: { pane: TodayRailPane; onAction: () => void }): JSX.Element {
    const { shortcutData, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { recents, recentsLoading } = useValues(recentItemsModel)
    const { peopleRecents, monitorRecents, releaseRecents } = useValues(todayRecentsLogic)
    const localRecents: { type: string; name: string; href: string }[] =
        pane === 'people' ? peopleRecents : pane === 'monitor' ? monitorRecents : []
    const pins = railPreviewItems(
        pane === 'release'
            ? namedReleaseEntries(
                  shortcutData.filter((entry) => !!entry.ref),
                  releaseRecents
              )
            : shortcutData,
        pane
    )
    const recentEntries =
        pane === 'release' ? releaseRecentEntries(recents, releaseRecents) : localRecents.map(localRecentEntry)
    const recentRows = railRecentItems(railPreviewItems(recentEntries, pane), pins)

    return (
        <TodayRailPreviewList
            pane={pane}
            title={TODAY_PANES[pane].label}
            pins={pins}
            recents={recentRows}
            loading={shortcutDataLoading || (pane === 'release' && recentsLoading)}
            onAction={onAction}
        />
    )
}
