import { useActions } from 'kea'
import { router } from 'kea-router'
import { memo } from 'react'

import { IconArchive } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { LinkListItem } from 'lib/ui/LinkListItem/LinkListItem'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { tasksLogic } from '../../../logics/tasksLogic'
import { Task, TaskRunStatus } from '../../../types/taskTypes'

const IN_PROGRESS_STATUSES = new Set<TaskRunStatus>([TaskRunStatus.QUEUED, TaskRunStatus.IN_PROGRESS])

// Compact "time ago" using a single largest unit, e.g. 18m, 1h, 7d.
function compactTimeAgo(iso: string): string {
    const seconds = dayjs().diff(dayjs(iso), 'second')
    if (seconds < 60) {
        return 'now'
    }
    return humanFriendlyDuration(seconds, { maxUnits: 1 })
}

// Memoized: the parent re-renders the whole list on every task projection, but a row only changes
// when its task or active state does.
export const TaskListItem = memo(function TaskListItem({
    task,
    isActive,
}: {
    task: Task
    isActive: boolean
}): JSX.Element {
    const { deleteTask } = useActions(tasksLogic)

    const displayTitle = task.title || task.slug
    // "Started" reflects when the latest run began; fall back to creation for never-run tasks.
    const startedAt = task.latest_run?.created_at ?? task.created_at
    const isInProgress = task.latest_run ? IN_PROGRESS_STATUSES.has(task.latest_run.status) : false

    return (
        <LinkListItem.Root>
            <LinkListItem.Group>
                <Link
                    to={urls.taskDetail(task.id)}
                    onClick={(e) => {
                        // Let cmd/ctrl/middle-click open a new tab natively.
                        if (e.metaKey || e.ctrlKey || e.button === 1) {
                            return
                        }
                        e.preventDefault()
                        router.actions.push(urls.taskDetail(task.id))
                    }}
                    buttonProps={{
                        active: isActive,
                        fullWidth: true,
                        // Taller tap target on mobile (min-height wins over the base menu-item height).
                        className: 'group',
                        menuItem: true,
                    }}
                    tooltip={displayTitle}
                    tooltipPlacement="right"
                >
                    <LinkListItem.Content
                        title={displayTitle}
                        isLoading={isInProgress}
                        meta={compactTimeAgo(startedAt)}
                    />
                </Link>
                <LinkListItem.Trigger />
            </LinkListItem.Group>
            <LinkListItem.Actions>
                <DropdownMenuGroup>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive menuItem variant="danger" onClick={() => deleteTask({ taskId: task.id })}>
                            <IconArchive className="size-4 text-danger" />
                            <span className="text-danger">Archive task</span>
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </LinkListItem.Actions>
        </LinkListItem.Root>
    )
})
