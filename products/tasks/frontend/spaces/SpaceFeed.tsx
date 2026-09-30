import { useActions, useValues } from 'kea'

import { TodayPaneGroup } from '~/layout/today/TodayPaneGroup'
import { TodayPaneState } from '~/layout/today/TodayPaneState'
import { TodaySessionRow } from '~/layout/today/TodaySessionRow'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceFeed({ id }: { id: string }): JSX.Element {
    const { feedGroups, sessionsLoading, sessionsUnavailable } = useValues(spaceSceneLogic({ id }))
    const { loadSessions } = useActions(spaceSceneLogic({ id }))
    const { pinnedItems } = useValues(todaySpacesLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))

    if (sessionsLoading && !feedGroups.length) {
        return <TodayPaneState loading />
    }
    if (sessionsUnavailable && !feedGroups.length) {
        return (
            <TodayPaneState
                message="This space’s sessions didn’t load."
                onRetry={() => loadSessions()}
                retrying={sessionsLoading}
                retryDataAttr="today-space-feed-retry"
            />
        )
    }
    if (!feedGroups.length) {
        return <TodayPaneState message="No sessions in this space yet." />
    }
    return (
        <div className="flex max-w-2xl flex-col gap-3">
            {feedGroups.map((group) => (
                <TodayPaneGroup key={group.key} label={group.label}>
                    {group.items.map((item) => (
                        <TodaySessionRow
                            key={item.id}
                            item={item}
                            pinned={pinnedIds.has(item.id)}
                            dataAttr="today-space-feed-session"
                        />
                    ))}
                </TodayPaneGroup>
            ))}
        </div>
    )
}
