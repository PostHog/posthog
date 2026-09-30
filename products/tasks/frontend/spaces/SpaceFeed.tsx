import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconCloud } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Skeleton,
    Text,
    cn,
} from '@posthog/quill'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { SpaceFeedCard } from './SpaceFeedCard'
import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceFeed({ id }: { id: string }): JSX.Element {
    const { feedGroups, sessionsById, sessionsLoading, sessionsUnavailable } = useValues(spaceSceneLogic({ id }))
    const { loadSessions } = useActions(spaceSceneLogic({ id }))
    const { pinnedItems, unreadSessionIds } = useValues(todaySpacesLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))

    if (sessionsLoading && !feedGroups.length) {
        return (
            <div className="flex max-w-3xl flex-col gap-3 px-2 py-2">
                <Skeleton className="h-4 w-1/4" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
            </div>
        )
    }
    if (sessionsUnavailable && !feedGroups.length) {
        return (
            <div className="flex flex-col items-start gap-2 px-2 py-2">
                <Text size="sm" variant="muted">
                    This space’s sessions didn’t load.
                </Text>
                <Button
                    variant="outline"
                    size="sm"
                    loading={sessionsLoading}
                    onClick={() => loadSessions()}
                    data-attr="today-space-feed-retry"
                >
                    Try again
                </Button>
            </div>
        )
    }
    if (!feedGroups.length) {
        return (
            <Empty className="py-12">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconCloud />
                    </EmptyMedia>
                    <EmptyTitle>No sessions yet</EmptyTitle>
                    <EmptyDescription>
                        Sessions that you or your agents start in this space show up here.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }
    return (
        <div className="flex max-w-3xl flex-col gap-2">
            {feedGroups.map((group, index) => (
                <Fragment key={group.key}>
                    <Text size="xs" variant="muted" className={cn('block px-1', index === 0 ? 'pt-1' : 'pt-4')}>
                        {group.label}
                    </Text>
                    {group.items.map((item) =>
                        sessionsById[item.id] ? (
                            <SpaceFeedCard
                                key={item.id}
                                task={sessionsById[item.id]}
                                pinned={pinnedIds.has(item.id)}
                                unread={unreadSessionIds.has(item.id)}
                            />
                        ) : null
                    )}
                </Fragment>
            ))}
        </div>
    )
}
