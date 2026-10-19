import { useActions, useValues } from 'kea'

import { IconArchive } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyHeader,
    EmptyTitle,
    Skeleton,
    Spinner,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill-primitives'

import { taskHistoryLogic } from '../../logics/taskHistoryLogic'
import { tasksLogic } from '../../logics/tasksLogic'
import { compactTimeAgo, isTaskInProgress } from '../../scenes/TaskTracker/components/taskHistoryUtils'
import { taskTrackerSceneLogic } from '../../scenes/TaskTracker/taskTrackerSceneLogic'

export function QuillTaskHistoryList(): JSX.Element {
    const { history, historyLoading } = useValues(taskHistoryLogic)
    const { openExistingTask } = useActions(taskTrackerSceneLogic)
    const { deleteTask } = useActions(tasksLogic)

    if (historyLoading && !history.length) {
        return (
            <div className="flex w-full flex-col gap-2">
                <Skeleton className="h-11" />
                <Skeleton className="h-11 opacity-80" />
                <Skeleton className="h-11 opacity-60" />
            </div>
        )
    }

    if (!history.length) {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>No tasks yet</EmptyTitle>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className="flex w-full flex-col">
            {history.map((task) => (
                // The archive button sits beside the row, not inside it, since a button can't nest in another.
                // It takes the time's place while the row is hovered or focused.
                <div key={task.id} className="group/row relative flex items-center">
                    <Button
                        size="sm"
                        left
                        className="w-full min-w-0 justify-between gap-2"
                        onClick={() => openExistingTask(task)}
                        data-attr="task-open-history-card"
                    >
                        <span className="min-w-0 truncate">{task.title || task.slug}</span>
                        <span className="shrink-0 group-focus-within/row:invisible group-hover/row:invisible">
                            {isTaskInProgress(task) ? (
                                <Spinner aria-label="Working" />
                            ) : (
                                <Text size="xs" variant="muted" render={<span translate="no" />}>
                                    {compactTimeAgo(task.updated_at)}
                                </Text>
                            )}
                        </span>
                    </Button>
                    <Tooltip>
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="icon-xs"
                                    aria-label="Archive task"
                                    className="absolute end-1 text-muted-foreground opacity-0 group-focus-within/row:opacity-100 group-hover/row:opacity-100 hover:text-foreground"
                                    onClick={() => deleteTask({ taskId: task.id })}
                                />
                            }
                        >
                            <IconArchive />
                        </TooltipTrigger>
                        <TooltipContent>Archive task</TooltipContent>
                    </Tooltip>
                </div>
            ))}
        </div>
    )
}
