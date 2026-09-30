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
import { SpaceFeedControls } from './SpaceFeedControls'
import { SpaceFeedListRow } from './SpaceFeedListRow'
import { SpaceFeedPullRequestRow } from './SpaceFeedPullRequestRow'
import { spaceFeedViewLogic } from './spaceFeedViewLogic'
import { spaceSceneLogic } from './spaceSceneLogic'

export function SpaceFeed({ id }: { id: string }): JSX.Element {
    const {
        feedItems,
        feedSections,
        feedSourceOptions,
        feedRepositories,
        sessionsById,
        sessionsLoading,
        sessionsUnavailable,
    } = useValues(spaceSceneLogic({ id }))
    const { loadSessions } = useActions(spaceSceneLogic({ id }))
    const { view, filtersActive } = useValues(spaceFeedViewLogic)
    const { clearFilters } = useActions(spaceFeedViewLogic)
    const { pinnedItems, unreadSessionIds } = useValues(todaySpacesLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))
    const listRows = view === 'list'

    if (sessionsLoading && !feedItems.length) {
        return (
            <div className="flex flex-col gap-3 px-2 py-2">
                <Skeleton className="h-4 w-1/4" />
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
            </div>
        )
    }
    if (sessionsUnavailable && !feedItems.length) {
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
    if (!feedItems.length) {
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
            <SpaceFeedControls sourceOptions={feedSourceOptions} />
            {!feedSections.length && (
                <div className="flex flex-col items-start gap-2 px-2 pt-6">
                    <Text size="sm" variant="muted">
                        {filtersActive ? 'Nothing here matches these filters.' : 'No pull requests in this space yet.'}
                    </Text>
                    {filtersActive && (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={clearFilters}
                            data-attr="today-space-feed-clear-filters"
                        >
                            Clear filters
                        </Button>
                    )}
                </div>
            )}
            {feedSections.map((section) => (
                <Fragment key={section.key}>
                    {section.label !== null &&
                        (listRows ? (
                            <Text
                                size="xxs"
                                weight="medium"
                                variant="muted"
                                className="px-2 pt-3 pb-1 tracking-wider uppercase"
                            >
                                {section.label}
                            </Text>
                        ) : (
                            <div className="flex items-center gap-3 pt-5 pb-2">
                                <Separator className="flex-1" />
                                <Text
                                    render={<span />}
                                    size="xxs"
                                    weight="semibold"
                                    variant="muted"
                                    className="shrink-0 tracking-wider uppercase"
                                >
                                    {section.label}
                                </Text>
                                <Separator className="flex-1" />
                            </div>
                        ))}
                    {section.entries.map((entry) => {
                        const task = sessionsById[entry.item.id]
                        if (!task) {
                            return null
                        }
                        // List rows are ruled apart, like PostHog Desktop's.
                        const rowClassName = 'border-b border-border last:border-b-0'
                        if (entry.kind === 'pr') {
                            const row = (
                                <SpaceFeedPullRequestRow
                                    key={entry.key}
                                    pullRequest={entry.pullRequest}
                                    session={entry.item}
                                    author={task.created_by ?? null}
                                    listRow={listRows}
                                />
                            )
                            return listRows ? (
                                <div key={entry.key} className={rowClassName}>
                                    {row}
                                </div>
                            ) : (
                                row
                            )
                        }
                        return listRows ? (
                            <div key={entry.key} className={rowClassName}>
                                <SpaceFeedListRow
                                    task={task}
                                    pinned={pinnedIds.has(task.id)}
                                    unread={unreadSessionIds.has(task.id)}
                                />
                            </div>
                        ) : (
                            <SpaceFeedCard
                                key={entry.key}
                                task={task}
                                pinned={pinnedIds.has(task.id)}
                                unread={unreadSessionIds.has(task.id)}
                                repository={feedRepositories[task.id] ?? null}
                            />
                        )
                    })}
                </Fragment>
            ))}
        </div>
    )
}
