import { CSSProperties, useEffect, useRef } from 'react'
import { List, useDynamicRowHeight } from 'react-window'

import { AutoSizer } from 'lib/components/AutoSizer'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { Task } from '../../../types/taskTypes'
import { TaskListItem } from './TaskListItem'

// Menu-item row height; the dynamic measurer corrects rows whose title wraps to two lines.
const DEFAULT_TASK_ROW_HEIGHT = 40
// Start fetching the next page this many rows before the end so it lands before the user hits the bottom.
const LOAD_MORE_THRESHOLD = 5

interface TaskRowProps {
    tasks: Task[]
    selectedTaskId: string | null
    dynamicRowHeight: ReturnType<typeof useDynamicRowHeight>
}

function TaskRow({
    index,
    style,
    tasks,
    selectedTaskId,
    dynamicRowHeight,
}: {
    ariaAttributes: Record<string, unknown>
    index: number
    style: CSSProperties
} & TaskRowProps): JSX.Element {
    const rowRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (rowRef.current) {
            return dynamicRowHeight.observeRowElements([rowRef.current])
        }
    }, [dynamicRowHeight])

    // The trailing row past the end of `tasks` is the infinite-scroll loader.
    const task = tasks[index]

    return (
        <div ref={rowRef} style={style} data-index={index} className="px-4 lg:px-0">
            {task ? (
                <TaskListItem task={task} isActive={task.id === selectedTaskId} />
            ) : (
                <div className="flex items-center justify-center py-3">
                    <Spinner />
                </div>
            )}
        </div>
    )
}

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
    const dynamicRowHeight = useDynamicRowHeight({ defaultRowHeight: DEFAULT_TASK_ROW_HEIGHT })

    // One extra row hosts the loader spinner while more pages remain.
    const rowCount = tasks.length + (hasMore ? 1 : 0)

    return (
        <AutoSizer
            renderProp={({ height, width }) =>
                height && width ? (
                    <List<TaskRowProps>
                        style={{ height, width }}
                        className="py-4 overflow-x-hidden"
                        overscanCount={10}
                        rowCount={rowCount}
                        rowHeight={dynamicRowHeight}
                        rowComponent={TaskRow}
                        rowProps={{ tasks, selectedTaskId, dynamicRowHeight }}
                        onRowsRendered={({ stopIndex }) => {
                            if (hasMore && !loadingMore && stopIndex >= tasks.length - LOAD_MORE_THRESHOLD) {
                                onLoadMore()
                            }
                        }}
                    />
                ) : null
            }
        />
    )
}
