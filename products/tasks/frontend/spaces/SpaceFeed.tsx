import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { Button, Separator, Skeleton, Text } from '@posthog/quill'

import { todaySpacesLogic } from '~/layout/today/todaySpacesLogic'

import { SpaceFeedCanvasRow } from './SpaceFeedCanvasRow'
import { SpaceFeedCard } from './SpaceFeedCard'
import { SpaceFeedControls } from './SpaceFeedControls'
import { SPACE_FEED_TYPES, SpaceFeedType } from './spaceFeedEntries'
import { SpaceFeedListRow } from './SpaceFeedListRow'
import { SpaceFeedPullRequestRow } from './SpaceFeedPullRequestRow'
import { spaceFeedViewLogic } from './spaceFeedViewLogic'
import { SpaceFeedSourceStatus, spaceSceneLogic } from './spaceSceneLogic'

const EMPTY_NOUNS: Record<SpaceFeedType, string> = { task: 'sessions', canvas: 'canvases', pr: 'pull requests' }

/** Names what the shown types would list, like "No canvases or pull requests in this space yet." */
function emptyNote(types: SpaceFeedType[]): string {
    const nouns = SPACE_FEED_TYPES.filter(({ value }) => types.includes(value)).map(({ value }) => EMPTY_NOUNS[value])
    const last = nouns.pop()
    return `No ${nouns.length ? `${nouns.join(', ')} or ${last}` : last} in this space yet.`
}

export function SpaceFeed({ id }: { id: string }): JSX.Element {
    const {
        canvasesLoading,
        feedSections,
        feedSourceOptions,
        feedRepositories,
        feedStatus,
        sessionsById,
        sessionsLoading,
    } = useValues(spaceSceneLogic({ id }))
    const { loadCanvases, loadSessions } = useActions(spaceSceneLogic({ id }))
    const { types, view, filtersActive } = useValues(spaceFeedViewLogic)
    const { clearFilters } = useActions(spaceFeedViewLogic)
    const { pinnedItems, unreadSessionIds } = useValues(todaySpacesLogic)
    const pinnedIds = new Set(pinnedItems.map((item) => item.id))
    const listRows = view === 'list'
    const typeStatus = (type: SpaceFeedType): SpaceFeedSourceStatus =>
        type === 'canvas' ? feedStatus.canvases : feedStatus.sessions
    const feedPending = !feedSections.length && types.some((type) => typeStatus(type) === 'loading')
    const emptyTypes = types.filter((type) => typeStatus(type) === 'ready')
    const feedEmpty = !feedSections.length && !feedPending && emptyTypes.length > 0

    return (
        // No gap: the cards' own margins and the separators' padding space the feed, like PostHog Desktop.
        <div className="flex flex-col">
            <SpaceFeedControls sourceOptions={feedSourceOptions} />
            {feedStatus.sessions === 'failed' && (
                <div className="flex flex-col items-start gap-2 px-2 pt-4">
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
            )}
            {feedStatus.canvases === 'failed' && (
                <div className="flex flex-col items-start gap-2 px-2 pt-4">
                    <Text size="sm" variant="muted">
                        This space’s canvases didn’t load.
                    </Text>
                    <Button
                        variant="outline"
                        size="sm"
                        loading={canvasesLoading}
                        onClick={() => loadCanvases()}
                        data-attr="today-space-feed-canvases-retry"
                    >
                        Try again
                    </Button>
                </div>
            )}
            {feedPending && (
                <div className="flex flex-col gap-3 px-2 pt-6">
                    <Skeleton className="h-4 w-1/4" />
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-4 w-2/3" />
                </div>
            )}
            {feedEmpty && (
                <div className="flex flex-col items-start gap-2 px-2 pt-6">
                    <Text size="sm" variant="muted">
                        {filtersActive ? 'Nothing here matches these filters.' : emptyNote(emptyTypes)}
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
                        // List rows are ruled apart, like PostHog Desktop's.
                        const rowClassName = 'border-b border-border last:border-b-0'
                        if (entry.kind === 'canvas') {
                            const row = <SpaceFeedCanvasRow key={entry.key} canvas={entry.canvas} listRow={listRows} />
                            return listRows ? (
                                <div key={entry.key} className={rowClassName}>
                                    {row}
                                </div>
                            ) : (
                                row
                            )
                        }
                        const task = sessionsById[entry.item.id]
                        if (!task) {
                            return null
                        }
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
