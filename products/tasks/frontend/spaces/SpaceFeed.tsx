import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { SpaceFeedCard } from './SpaceFeedCard'
import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceFeed({ id }: { id: string }): JSX.Element {
    const { feedGroups, sessionsById, sessionsLoading, sessionsUnavailable } = useValues(spaceSceneLogic({ id }))
    const { loadSessions } = useActions(spaceSceneLogic({ id }))
    const { pinnedItems } = useValues(todaySpacesLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))

    if (sessionsLoading && !feedGroups.length) {
        return (
            <div className="TodayPane__state mx-auto w-full max-w-5xl">
                <Spinner />
            </div>
        )
    }
    if (sessionsUnavailable && !feedGroups.length) {
        return (
            <div className="TodayPane__state mx-auto w-full max-w-5xl">
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
        return <div className="TodayPane__state mx-auto w-full max-w-5xl">No sessions in this space yet.</div>
    }
    return (
        <div className="mx-auto w-full max-w-5xl">
            {feedGroups.map((group) => (
                <Fragment key={group.key}>
                    <div className="TodaySpaceFeed__day">{group.label}</div>
                    {group.items.map((item) =>
                        sessionsById[item.id] ? (
                            <SpaceFeedCard key={item.id} task={sessionsById[item.id]} pinned={pinnedIds.has(item.id)} />
                        ) : null
                    )}
                </Fragment>
            ))}
        </div>
    )
}
