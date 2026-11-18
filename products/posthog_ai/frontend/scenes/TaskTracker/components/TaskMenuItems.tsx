import type { ReactNode } from 'react'

import { IconArchive, IconInfo } from '@posthog/icons'

import type { TodayMenuParts } from '~/layout/today/todayMenuParts'

import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { DebugLogsMenuItem } from '../../../components/DebugLogsMenuItem'
import type { Task } from '../../../types/taskTypes'
import { TaskMenuFacts } from './TaskMenuFacts'

export interface TaskMenuItemsProps {
    parts: TodayMenuParts
    task: Task
    run: TaskRunDetailDTOApi | null
    onArchive: () => void
    placement?: ReactNode
}

export function TaskMenuItems({ parts, task, run, onArchive, placement }: TaskMenuItemsProps): JSX.Element {
    return (
        <>
            {placement && (
                <>
                    {placement}
                    <parts.Separator />
                </>
            )}
            <DebugLogsMenuItem parts={parts} />
            <parts.Item variant="destructive" onClick={onArchive} dataAttr="task-archive">
                <IconArchive />
                Archive task
            </parts.Item>
            <parts.Separator />
            <parts.Section
                label={
                    <>
                        <IconInfo />
                        Task details
                    </>
                }
                title="Task details"
                dataAttr="task-details"
            >
                <TaskMenuFacts task={task} run={run} />
            </parts.Section>
        </>
    )
}
