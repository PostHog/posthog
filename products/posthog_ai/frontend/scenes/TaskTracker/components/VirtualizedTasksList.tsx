import { useVirtualizer } from '@tanstack/react-virtual'
import { useCallback, useEffect, useRef } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { Task } from '../../../types/taskTypes'
import { TaskListItem } from './TaskListItem'

// Menu-item row height; the virtualizer's dynamic measurement corrects rows whose title wraps to two lines.
const DEFAULT_TASK_ROW_HEIGHT = 40
// Start fetching the next page this many rows before the end so it lands before the user hits the bottom.
const LOAD_MORE_THRESHOLD = 5

interface VirtualizedTasksListProps {
    tasks: Task[]
    /** Currently selected task id, used to highlight its row. */
    selectedTaskId: string | null
    /** Whether another page can be fetched (the response still has a `next` cursor). */
    hasMore: boolean
    /** Whether a page fetch is already in flight, to avoid duplicate loads. */
    loadingMore: boolean
    onLoadMore: () => void
}

export function VirtualizedTasksList({
    tasks,
    selectedTaskId,
    hasMore,
    loadingMore,
    onLoadMore,
}: VirtualizedTasksListProps): JSX.Element {
    const scrollRef = useRef<HTMLDivElement>(null)

    // Stable per-task keys so pagination appends don't remount already-measured rows.
    const getItemKey = useCallback((index: number): string => tasks[index]?.id ?? '__tasks_loader__', [tasks])

    const virtualizer = useVirtualizer({
        // One extra row hosts the loader spinner while more pages remain.
        count: tasks.length + (hasMore ? 1 : 0),
        getScrollElement: () => scrollRef.current,
        estimateSize: () => DEFAULT_TASK_ROW_HEIGHT,
        overscan: 10,
        paddingStart: 16,
        paddingEnd: 16,
        getItemKey,
    })

    const virtualItems = virtualizer.getVirtualItems()
    const lastRenderedIndex = virtualItems[virtualItems.length - 1]?.index ?? -1

    useEffect(() => {
        if (hasMore && !loadingMore && lastRenderedIndex >= tasks.length - LOAD_MORE_THRESHOLD) {
            onLoadMore()
        }
    }, [hasMore, loadingMore, lastRenderedIndex, tasks.length, onLoadMore])

    return (
        <div ref={scrollRef} className="h-full overflow-y-auto overflow-x-hidden">
            <div style={{ position: 'relative', width: '100%', height: virtualizer.getTotalSize() }}>
                {virtualItems.map((virtualRow) => {
                    const task = tasks[virtualRow.index]

                    return (
                        <div
                            key={virtualRow.key}
                            data-index={virtualRow.index}
                            ref={virtualizer.measureElement}
                            className="px-4 lg:px-0"
                            style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                width: '100%',
                                transform: `translateY(${virtualRow.start}px)`,
                            }}
                        >
                            {task ? (
                                <TaskListItem task={task} isActive={task.id === selectedTaskId} />
                            ) : (
                                <div className="flex items-center justify-center py-3">
                                    <Spinner />
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
