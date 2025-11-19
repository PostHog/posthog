import { type LemonBadgeProps } from '@posthog/lemon-ui'

import { TaskRunStatus } from '../types'

export const TASK_STATUS_CONFIG: Record<
    TaskRunStatus | 'all' | 'not_started',
    { status: LemonBadgeProps['status']; label: string }
> = {
    all: { status: 'muted', label: 'All' },
    not_started: { status: 'muted', label: 'Not started' },
    [TaskRunStatus.STARTED]: { status: 'primary', label: 'Started' },
    [TaskRunStatus.IN_PROGRESS]: { status: 'warning', label: 'In progress' },
    [TaskRunStatus.COMPLETED]: { status: 'success', label: 'Completed' },
    [TaskRunStatus.FAILED]: { status: 'danger', label: 'Failed' },
}
