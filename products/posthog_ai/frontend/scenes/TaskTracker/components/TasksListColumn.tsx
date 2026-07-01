import { useActions, useValues } from 'kea'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'
import { Input } from '@posthog/quill-primitives'

import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { tasksLogic } from '../../../logics/tasksLogic'
import { TaskAssigneeFilterMenu } from './TaskAssigneeFilterMenu'
import { VirtualizedTasksList } from './VirtualizedTasksList'

interface TasksListColumnProps {
    /** Currently selected task id, used to highlight its row. Null when showing the composer. */
    selectedTaskId: string | null
    /** On mobile the column is the whole screen: the list scrolls in its own container and a floating button creates a task. */
    isMobile?: boolean
}

export function TasksListColumn({ selectedTaskId, isMobile = false }: TasksListColumnProps): JSX.Element {
    const {
        tasks,
        tasksLoading,
        tasksError,
        tasksNext,
        tasksLoadingMore,
        searchQuery,
        assigneeFilter,
        taskListParams,
    } = useValues(tasksLogic)
    const { loadTasks, loadMoreTasks, setSearchQuery } = useActions(tasksLogic)

    // With tasks present the list is virtualized (it fills a bounded-height container); the empty,
    // loading, and error states render as plain blocks since they need no windowing.
    const content =
        tasks.length > 0 ? (
            <VirtualizedTasksList
                tasks={tasks}
                selectedTaskId={selectedTaskId}
                hasMore={!!tasksNext}
                loadingMore={tasksLoadingMore}
                onLoadMore={() => loadMoreTasks()}
            />
        ) : tasksLoading ? (
            <div className="flex flex-col gap-1 px-1">
                <LemonSkeleton className="h-8" />
                <LemonSkeleton className="h-8 opacity-60" />
                <LemonSkeleton className="h-8 opacity-30" />
            </div>
        ) : // A failed load with no cached tasks must not look like "No tasks yet" — show the error + a retry.
        // A refresh that fails while tasks already exist keeps the stale list rather than wiping good data.
        tasksError ? (
            <LemonBanner
                type="error"
                className="mx-1"
                action={{ children: 'Retry', onClick: () => loadTasks(taskListParams) }}
                data-attr="tasks-load-error"
            >
                <p className="mb-0">We couldn't load your tasks.</p>
                <p className="text-muted mb-0">{tasksError}</p>
            </LemonBanner>
        ) : (
            <div className="flex flex-col items-center justify-center text-center py-8 text-muted">
                <p className="text-sm mb-0">
                    {searchQuery || assigneeFilter !== 'for_you' ? 'No tasks match your filters' : 'No tasks yet'}
                </p>
            </div>
        )

    const searchInput = (
        <div className="flex items-center gap-1">
            <Input
                type="search"
                placeholder="Search tasks…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                data-attr="tasks-search"
                className="flex-1"
            />
            <TaskAssigneeFilterMenu />
        </div>
    )

    if (isMobile) {
        // The virtualized list owns its own scroll inside this bounded-height column. The trailing
        // spacer ends the list above the floating create button so it never hides the last row.
        return (
            <div className="flex flex-col flex-1 min-h-0">
                <div className="shrink-0 lg:px-1">{searchInput}</div>
                <LemonDivider className="mb-0 mt-4" />
                <div className={cn('flex flex-col flex-1 min-h-0', tasks.length > 0 && '-mx-4')}>{content}</div>
                <div className="shrink-0 h-20" />
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    to={urls.taskNew()}
                    size="large"
                    data-attr="tasks-new-mobile"
                    className="fixed bottom-4 right-4 z-20 shadow-md"
                >
                    New task
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full min-h-0">
            <div className="flex items-center justify-between gap-1 py-2 pr-2 pl-1 shrink-0">
                <span className="text-sm font-semibold pl-1">Tasks</span>
                <Link
                    to={urls.taskNew()}
                    data-attr="tasks-new"
                    buttonProps={{ iconOnly: true, variant: 'outline' }}
                    tooltip="New task"
                >
                    <IconPlusSmall className="size-4" />
                </Link>
            </div>
            <div className="px-1 pb-4 shrink-0">{searchInput}</div>
            <LemonDivider className="m-0 shrink-0" />

            {/* flex-1 min-h-0 gives the virtualized list a bounded height to fill (it owns the scroll). */}
            <div className="flex flex-col flex-1 min-h-0">{content}</div>
        </div>
    )
}
