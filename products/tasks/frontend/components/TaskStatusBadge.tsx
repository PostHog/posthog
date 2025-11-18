import { LemonTag } from '@posthog/lemon-ui'

import { Task, TaskRunStatus } from '../types'

const statusConfig: Record<TaskRunStatus, { type: 'primary' | 'success' | 'danger' | 'warning'; label: string }> = {
    [TaskRunStatus.STARTED]: { type: 'primary', label: 'Started' },
    [TaskRunStatus.IN_PROGRESS]: { type: 'warning', label: 'In progress' },
    [TaskRunStatus.COMPLETED]: { type: 'success', label: 'Completed' },
    [TaskRunStatus.FAILED]: { type: 'danger', label: 'Failed' },
}

export function TaskStatusBadge({ task }: { task: Task }): JSX.Element {
    if (!task.latest_run) {
        return <LemonTag type="default">Not started</LemonTag>
    }

    const config = statusConfig[task.latest_run.status]
    return <LemonTag type={config.type}>{config.label}</LemonTag>
}
