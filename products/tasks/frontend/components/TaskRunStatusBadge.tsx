import { LemonTag } from '@posthog/lemon-ui'

import { TASK_STATUS_CONFIG } from '../lib/task-status'
import { TaskRun } from '../types'

const STATUS_TO_TAG_TYPE: Record<string, 'primary' | 'success' | 'danger' | 'warning' | 'default'> = {
    primary: 'primary',
    success: 'success',
    danger: 'danger',
    warning: 'warning',
    muted: 'default',
}

export function TaskRunStatusBadge({ run }: { run: TaskRun }): JSX.Element {
    const config = TASK_STATUS_CONFIG[run.status]
    const tagType = STATUS_TO_TAG_TYPE[config.status || 'muted'] || 'default'

    return <LemonTag type={tagType}>{config.label}</LemonTag>
}
