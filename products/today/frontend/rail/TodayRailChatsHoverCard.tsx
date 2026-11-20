import { useValues } from 'kea'

import { urls } from 'scenes/urls'

import { newestByName } from '~/layout/today/todayNewestByName'
import { TodaySessionIcon } from '~/layout/today/TodaySessionIcon'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'
import { TodayWorkItem } from '~/layout/today/todayWorkItems'

import { RAIL_RECENTS_LIMIT } from './todayRailPreviewItems'
import { TodayRailPreviewItem, TodayRailPreviewList } from './TodayRailPreviewList'

function previewItem(item: TodayWorkItem): TodayRailPreviewItem {
    return {
        name: item.title || (item.kind === 'session' ? 'Untitled session' : 'Untitled chat'),
        href: item.kind === 'session' ? urls.aiTask(item.id) : urls.ai(item.id),
        icon: <TodaySessionIcon item={item} />,
    }
}

export function TodayRailChatsHoverCard({ onAction }: { onAction: () => void }): JSX.Element {
    const { pinnedItems, allRecentItems, pinnedTasksLoading, recentLoading, recentTasksUnavailable } =
        useValues(todaySpacesLogic)

    return (
        <TodayRailPreviewList
            title="Chats"
            pins={pinnedItems.map(previewItem)}
            recents={newestByName(
                allRecentItems,
                (item) => item.title || '',
                (item) => item.id,
                RAIL_RECENTS_LIMIT
            ).map(previewItem)}
            loading={pinnedTasksLoading || recentLoading}
            failed={recentTasksUnavailable}
            onAction={onAction}
        />
    )
}
