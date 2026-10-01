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
    Separator,
    Skeleton,
    Text,
} from '@posthog/quill'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { SpaceFeedCard } from './SpaceFeedCard'
import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceFeed({ id }: { id: string }): JSX.Element {
    const { feedGroups, feedRepositories, sessionsById, sessionsLoading, sessionsUnavailable } = useValues(
        spaceSceneLogic({ id })
    )
    const { loadSessions } = useActions(spaceSceneLogic({ id }))
    const { pinnedItems, unreadSessionIds } = useValues(todaySpacesLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))

    if (sessionsLoading && !feedGroups.length) {
        return (
            <div className="flex flex-col gap-3 px-2 py-2">
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
        // No gap: the cards' own margins and the separators' padding space the feed, like PostHog Desktop.
        <div className="flex flex-col">
            {feedGroups.map((group) => (
                <Fragment key={group.key}>
                    <div className="flex items-center gap-3 pt-5 pb-2">
                        <Separator className="flex-1" />
                        <Text
                            render={<span />}
                            size="xxs"
                            weight="semibold"
                            variant="muted"
                            className="shrink-0 tracking-wider uppercase"
                        >
                            {group.label}
                        </Text>
                        <Separator className="flex-1" />
                    </div>
                    {group.items.map((item) =>
                        sessionsById[item.id] ? (
                            <SpaceFeedCard
                                key={item.id}
                                task={sessionsById[item.id]}
                                pinned={pinnedIds.has(item.id)}
                                unread={unreadSessionIds.has(item.id)}
                                repository={feedRepositories[item.id] ?? null}
                            />
                        ) : null
                    )}
                </Fragment>
            ))}
        </div>
    )
}
