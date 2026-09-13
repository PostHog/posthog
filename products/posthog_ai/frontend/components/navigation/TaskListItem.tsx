import { useActions } from 'kea'

import { IconArchive, IconCloud, IconLaptop, IconListCheck } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuGroup, DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { LinkListItem } from 'lib/ui/LinkListItem/LinkListItem'
import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { urls } from 'scenes/urls'

import { tasksLogic } from '../../logics/tasksLogic'
import { TaskRunEnvironment } from '../../types/taskTypes'
import type { Task } from '../../types/taskTypes'
import { TaskRunLivenessDot } from '../TaskRunLivenessDot'

function compactTimeAgo(iso: string): string {
    const seconds = dayjs().diff(dayjs(iso), 'second')
    if (seconds < 60) {
        return 'now'
    }
    return humanFriendlyDuration(seconds, { maxUnits: 1 })
}

function getHref(taskId: string): string {
    return urls.aiTask(taskId)
}

function TaskTypeIcon({ task }: { task: Task }): JSX.Element {
    const environment = task.latest_run?.environment
    const label = environment === TaskRunEnvironment.CLOUD ? 'Cloud task' : 'Local task'

    return (
        <Tooltip title={environment ? label : 'Task'} placement="right">
            <span className="flex size-4 text-secondary opacity-50 group-hover:opacity-100 transition-all duration-50">
                {environment === TaskRunEnvironment.CLOUD ? (
                    <IconCloud />
                ) : environment === TaskRunEnvironment.LOCAL ? (
                    <IconLaptop />
                ) : (
                    <IconListCheck />
                )}
            </span>
        </Tooltip>
    )
}

function Content({ task }: { task: Task }): JSX.Element {
    const displayTitle = task.title || task.slug

    return (
        <>
            <TaskTypeIcon task={task} />
            <span className="flex-1 line-clamp-1 text-primary">{displayTitle}</span>
            {task.latest_run && <TaskRunLivenessDot status={task.latest_run.status} />}
            <span
                className={cn(
                    'opacity-30 text-xs pr-1.5 transition-opacity duration-100',
                    'group-hover:opacity-0 group-has-[[data-state=open]]:opacity-0 group-has-focus-within:opacity-0'
                )}
            >
                {compactTimeAgo(task.last_activity_at ?? task.updated_at)}
            </span>
        </>
    )
}

function Actions({ taskId }: { taskId: string }): JSX.Element {
    const { deleteTask } = useActions(tasksLogic)

    return (
        <LinkListItem.Actions>
            <DropdownMenuGroup>
                <DropdownMenuItem asChild>
                    <ButtonPrimitive menuItem variant="danger" onClick={() => deleteTask({ taskId })}>
                        <IconArchive className="size-4 text-danger" />
                        <span className="text-danger">Archive task</span>
                    </ButtonPrimitive>
                </DropdownMenuItem>
            </DropdownMenuGroup>
        </LinkListItem.Actions>
    )
}

export const TaskListItem = {
    Root: LinkListItem.Root,
    Group: LinkListItem.Group,
    Content,
    Trigger: LinkListItem.Trigger,
    Actions,
    getHref,
}
