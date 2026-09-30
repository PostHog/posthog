import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { TodaySessionRow } from '~/layout/today/TodaySessionRow'
import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceFeed({ id }: { id: string }): JSX.Element {
    const { feedGroups, sessionsLoading, sessionsUnavailable } = useValues(spaceSceneLogic({ id }))
    const { loadSessions } = useActions(spaceSceneLogic({ id }))
    const { pinnedItems } = useValues(todaySpacesLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))

    if (sessionsLoading && !feedGroups.length) {
        return (
            <div className="TodayPane__state">
                <Spinner />
            </div>
        )
    }
    if (sessionsUnavailable && !feedGroups.length) {
        return (
            <div className="TodayPane__state">
                <span>This space’s sessions didn’t load.</span>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={() => loadSessions()}
                    data-attr="today-space-feed-retry"
                >
                    Try again
                </LemonButton>
            </div>
        )
    }
    if (!feedGroups.length) {
        return <div className="TodayPane__state">No sessions in this space yet.</div>
    }
    return (
        <div className="TodaySpaceFeed">
            {feedGroups.map((group, index) => (
                <Fragment key={group.key}>
                    <div className={cn('TodayPane__group', index === 0 && 'TodayPane__group--first')}>
                        {group.label}
                    </div>
                    {group.items.map((item) => (
                        <TodaySessionRow
                            key={item.id}
                            item={item}
                            pinned={pinnedIds.has(item.id)}
                            dataAttr="today-space-feed-session"
                            surface="feed"
                        />
                    ))}
                </Fragment>
            ))}
        </div>
    )
}
