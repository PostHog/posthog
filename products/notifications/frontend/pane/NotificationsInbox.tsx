import { useActions, useValues } from 'kea'
import { KeyboardEvent, useEffect, useRef, useState } from 'react'

import { Button, Text } from '@posthog/quill'

import { NotificationActionRow } from './NotificationActionRow'
import { NotificationCompactRow } from './NotificationCompactRow'
import { NotificationPaneEntry, showsActionRow } from './notificationPaneEntries'
import { nextRowIndex, rowCommandForKey } from './notificationsPaneKeys'
import { notificationsPaneLogic } from './notificationsPaneLogic'

const ROW_SELECTOR = '[data-row-primary]'

function otherProjectName(entry: NotificationPaneEntry, currentTeamId: number | null): string | null {
    const { team_id } = entry.notification
    return team_id !== null && team_id !== currentTeamId ? (entry.projectName ?? 'Another project') : null
}

/** The notification rows: one Tab stop, arrows or j/k to move, E to archive, U to toggle read. */
export function NotificationsInbox(): JSX.Element {
    const { entries, activeKey, newCount, nextCursor, loadingMore, loadMoreFailed, showArchived, currentTeamId } =
        useValues(notificationsPaneLogic)
    const { archive, undoArchive, toggleRead, loadMore, showNewNotifications, setListIdle } =
        useActions(notificationsPaneLogic)
    const listRef = useRef<HTMLUListElement>(null)
    const scrollRef = useRef<HTMLDivElement>(null)
    const [focusIndex, setFocusIndex] = useState(0)
    const [hovered, setHovered] = useState(false)
    const refocusAfterChange = useRef(false)

    const rows = (): HTMLElement[] => [...(listRef.current?.querySelectorAll<HTMLElement>(ROW_SELECTOR) ?? [])]
    const focusedIndex = Math.min(focusIndex, Math.max(entries.length - 1, 0))

    useEffect(() => {
        if (!refocusAfterChange.current) {
            return
        }
        refocusAfterChange.current = false
        rows()[focusedIndex]?.focus()
    }, [entries, focusedIndex])

    const updateIdle = (pointerOver: boolean): void => {
        setHovered(pointerOver)
        setListIdle(!pointerOver && (scrollRef.current?.scrollTop ?? 0) === 0)
    }

    const onKeyDown = (event: KeyboardEvent<HTMLUListElement>): void => {
        const current = rows().indexOf(document.activeElement as HTMLElement)
        if (current === -1) {
            return
        }
        const next = nextRowIndex(current, entries.length, event.key)
        if (next !== null) {
            event.preventDefault()
            setFocusIndex(next)
            rows()[next]?.focus()
            return
        }
        const command = rowCommandForKey(event.key, event.shiftKey)
        const entry = entries[current]
        if (!command || !entry || event.metaKey || event.ctrlKey || event.altKey) {
            return
        }
        event.preventDefault()
        if (command === 'archive' && !showArchived) {
            refocusAfterChange.current = true
            archive(entry)
        } else if (command === 'undo_archive') {
            undoArchive()
        } else if (command === 'toggle_read' && !showArchived) {
            toggleRead(entry)
        }
    }

    return (
        <div className="relative flex min-h-0 flex-1 flex-col">
            {newCount > 0 && (
                <div className="pointer-events-none absolute inset-x-0 top-1 z-10 flex justify-center">
                    <Button
                        size="sm"
                        variant="primary"
                        className="pointer-events-auto shadow-md"
                        onClick={() => {
                            scrollRef.current?.scrollTo({ top: 0 })
                            showNewNotifications()
                        }}
                        data-attr="notifications-pane-show-new"
                    >
                        {newCount} new
                    </Button>
                </div>
            )}
            <div
                ref={scrollRef}
                className="TodayPane__scroll mt-1"
                onScroll={() => updateIdle(hovered)}
                onPointerEnter={() => updateIdle(true)}
                onPointerLeave={() => updateIdle(false)}
            >
                <ul
                    ref={listRef}
                    aria-label={showArchived ? 'Archived notifications' : 'Notifications'}
                    className="m-0 flex list-none flex-col gap-0.5 p-0"
                    onKeyDown={onKeyDown}
                >
                    {entries.map((entry, index) => {
                        const rowProps = {
                            entry,
                            active: entry.key === activeKey,
                            focusable: index === focusedIndex,
                            otherProjectName: otherProjectName(entry, currentTeamId),
                        }
                        return showsActionRow(entry) && !showArchived ? (
                            <NotificationActionRow key={entry.key} {...rowProps} />
                        ) : (
                            <NotificationCompactRow key={entry.key} {...rowProps} archived={showArchived} />
                        )
                    })}
                </ul>
                {loadMoreFailed ? (
                    <div className="flex items-center justify-between gap-2 px-2 py-3">
                        <Text size="sm" variant="muted">
                            Couldn't load more
                        </Text>
                        <Button
                            size="sm"
                            variant="outline"
                            onClick={loadMore}
                            data-attr="notifications-pane-retry-more"
                        >
                            Retry
                        </Button>
                    </div>
                ) : (
                    nextCursor && (
                        <div className="flex justify-center py-3">
                            <Button
                                size="sm"
                                loading={loadingMore}
                                onClick={loadMore}
                                data-attr="notifications-pane-load-more"
                            >
                                Load more
                            </Button>
                        </div>
                    )
                )}
            </div>
        </div>
    )
}
