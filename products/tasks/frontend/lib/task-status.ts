import { type LemonBadgeProps } from '@posthog/lemon-ui'

import { TaskRunStatus } from '../types'

export const TASK_STATUS_CONFIG: Record<
    TaskRunStatus | 'all' | 'not_started',
    { status: LemonBadgeProps['status']; label: string }
> = {
    all: { status: 'muted', label: 'All' },

    [TaskRunStatus.NOT_STARTED]: { status: 'muted', label: 'Not started' },
    [TaskRunStatus.QUEUED]: { status: 'muted', label: 'Queued' },
    [TaskRunStatus.IN_PROGRESS]: { status: 'primary', label: 'In progress' },
    [TaskRunStatus.COMPLETED]: { status: 'success', label: 'Completed' },
    [TaskRunStatus.FAILED]: { status: 'danger', label: 'Failed' },
    [TaskRunStatus.CANCELLED]: { status: 'danger', label: 'Cancelled' },
}
