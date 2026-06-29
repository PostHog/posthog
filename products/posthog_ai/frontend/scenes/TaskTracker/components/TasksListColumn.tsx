import { useActions, useValues } from 'kea'

import { IconPlus, IconPlusSmall } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'
import { Input } from '@posthog/quill-primitives'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { tasksLogic } from '../../../logics/tasksLogic'
import { TaskAssigneeFilterMenu } from './TaskAssigneeFilterMenu'
import { TaskListItem } from './TaskListItem'

interface TasksListColumnProps {
    /** Currently selected task id, used to highlight its row. Null when showing the composer. */
    selectedTaskId: string | null
    /** On mobile the column is the whole screen: the page scrolls and a floating button creates a task. */
    isMobile?: boolean
}

export function TasksListColumn({ selectedTaskId, isMobile = false }: TasksListColumnProps): JSX.Element {
    const { tasks, tasksLoading, tasksError, searchQuery, assigneeFilter, taskListParams } = useValues(tasksLogic)
    const { loadTasks, setSearchQuery } = useActions(tasksLogic)

    const rows =
        tasksLoading && tasks.length === 0 ? (
            <div className="flex flex-col gap-1 px-1">
                <LemonSkeleton className="h-8" />
                <LemonSkeleton className="h-8 opacity-60" />
                <LemonSkeleton className="h-8 opacity-30" />
            </div>
        ) : // A failed load with no cached tasks must not look like "No tasks yet" — show the error + a retry.
        // A refresh that fails while tasks already exist keeps the stale list rather than wiping good data.
        tasksError && tasks.length === 0 ? (
            <LemonBanner
                type="error"
                className="mx-1"
                action={{ children: 'Retry', onClick: () => loadTasks(taskListParams) }}
                data-attr="tasks-load-error"
            >
                <p className="mb-0">We couldn't load your tasks.</p>
                <p className="text-muted mb-0">{tasksError}</p>
            </LemonBanner>
        ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center text-center py-8 text-muted">
                <p className="text-sm mb-0">
                    {searchQuery || assigneeFilter !== 'for_you' ? 'No tasks match your filters' : 'No tasks yet'}
                </p>
            </div>
        ) : (
            tasks.map((task) => <TaskListItem key={task.id} task={task} isActive={task.id === selectedTaskId} />)
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
        // The page (main) scrolls — no inner scroll container. Extra bottom padding keeps the last
        // rows clear of the floating create button.
        return (
            <>
                <div className="px-1 pb-2">{searchInput}</div>
                <div className="flex flex-col gap-1 pb-24">{rows}</div>
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
            </>
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
            <div className="px-1 pb-2 shrink-0">{searchInput}</div>
            <LemonDivider className="m-0 shrink-0" />

            <ScrollableShadows
                direction="vertical"
                className="flex flex-col flex-1 min-h-0 overflow-hidden pt-2"
                innerClassName="pr-2"
                // Row gap + trailing space live on the content, not the scroll viewport: a single
                // Content child means a gap on the viewport is a no-op, and Chrome drops a scroll
                // container's `padding-bottom`, so `pb-4` only sticks here.
                contentClassName="flex flex-col gap-1 pb-4"
                styledScrollbars
            >
                {rows}
            </ScrollableShadows>
        </div>
    )
}
