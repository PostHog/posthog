import { useActions, useValues } from 'kea'

import { IconArchive } from '@posthog/icons'
import { LemonButton, LemonSkeleton, Link, Spinner } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { taskHistoryLogic } from '../../../logics/taskHistoryLogic'
import { tasksLogic } from '../../../logics/tasksLogic'
import { Task, TaskRunStatus } from '../../../types/taskTypes'
import { taskTrackerSceneLogic } from '../taskTrackerSceneLogic'

const IN_PROGRESS_STATUSES = new Set<TaskRunStatus>([TaskRunStatus.QUEUED, TaskRunStatus.IN_PROGRESS])

// Compact "time ago" using a single largest unit, e.g. 18m, 1h, 7d.
function compactTimeAgo(iso: string): string {
    const seconds = dayjs().diff(dayjs(iso), 'second')
    if (seconds < 60) {
        return 'now'
    }
    return humanFriendlyDuration(seconds, { maxUnits: 1 })
}

function isTaskInProgress(task: Task): boolean {
    return task.latest_run ? IN_PROGRESS_STATUSES.has(task.latest_run.status) : false
}

export function TaskHistoryPreview(): JSX.Element | null {
    const { history, historyLoading } = useValues(taskHistoryLogic)
    const { toggleHistory, openExistingTask } = useActions(taskTrackerSceneLogic)

    if (!history.length && !historyLoading) {
        return null
    }

    return (
        <div className="max-w-120 w-full self-center flex flex-col gap-2 px-3">
            <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium text-secondary mb-0">Recent tasks</h3>
                <LemonButton
                    size="small"
                    onClick={() => toggleHistory()}
                    data-attr="task-view-all-history"
                    tooltip="Open task history"
                    tooltipPlacement="bottom"
                >
                    View all
                </LemonButton>
            </div>
            {historyLoading && !history.length ? (
                <>
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                    <LemonSkeleton className="h-5 w-full" />
                </>
            ) : (
                history
                    .slice(0, 3)
                    .map((task) => <TaskHistoryPreviewRow key={task.id} task={task} onOpen={openExistingTask} />)
            )}
        </div>
    )
}

interface TaskHistoryRowProps {
    task: Task
    onOpen: (task: Task) => void
}

function TaskHistoryPreviewRow({ task, onOpen }: TaskHistoryRowProps): JSX.Element {
    return (
        <span className="flex items-center gap-2">
            <Link
                className="grow text-sm text-primary hover:text-accent-hover active:text-accent-active"
                data-attr="task-open-history-preview"
                to={urls.taskDetail(task.id)}
                onClick={(e) => {
                    e.preventDefault()
                    onOpen(task)
                }}
            >
                <div className="flex items-center gap-2">
                    <span className="flex-1 line-clamp-1">{task.title || task.slug}</span>
                </div>
            </Link>
            {isTaskInProgress(task) ? (
                <Spinner className="h-4 w-4" />
            ) : (
                <span className="text-right text-secondary whitespace-nowrap cursor-default">
                    {compactTimeAgo(task.updated_at)}
                </span>
            )}
        </span>
    )
}

export function TaskHistoryList(): JSX.Element {
    const { history, historyLoading } = useValues(taskHistoryLogic)
    const { openExistingTask } = useActions(taskTrackerSceneLogic)

    if (historyLoading && !history.length) {
        return (
            <div className="flex flex-col gap-2 w-full">
                <LemonSkeleton className="h-14" />
                <LemonSkeleton className="h-14 opacity-80" />
                <LemonSkeleton className="h-14 opacity-60" />
            </div>
        )
    }

    if (!history.length) {
        return (
            <div className="flex flex-col items-center justify-center text-center py-8 text-muted">
                <p className="text-sm mb-0">No tasks yet</p>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            {history.map((task) => (
                <TaskHistoryCard key={task.id} task={task} onOpen={openExistingTask} />
            ))}
        </div>
    )
}

function TaskHistoryCard({ task, onOpen }: TaskHistoryRowProps): JSX.Element {
    const { deleteTask } = useActions(tasksLogic)
    const { taskArchived } = useActions(taskHistoryLogic)

    return (
        <div
            className="p-3 flex flex-row bg-surface-primary rounded-lg gap-2 w-full items-center justify-between cursor-pointer"
            role="button"
            tabIndex={0}
            data-attr="task-open-history-card"
            onClick={() => onOpen(task)}
            onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    onOpen(task)
                }
            }}
        >
            <span className="flex-1 line-clamp-1 text-sm">{task.title || task.slug}</span>
            <div className="flex items-center gap-2 shrink-0">
                {isTaskInProgress(task) ? (
                    <Spinner className="h-4 w-4" />
                ) : (
                    <span className="text-secondary text-xs">{compactTimeAgo(task.updated_at)}</span>
                )}
                <LemonButton
                    size="small"
                    icon={<IconArchive />}
                    status="danger"
                    aria-label="Archive task"
                    onClick={(e) => {
                        e.stopPropagation()
                        deleteTask({ taskId: task.id })
                        taskArchived(task.id)
                    }}
                />
            </div>
        </div>
    )
}
