import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { Task, TaskRunStatus } from '../../../types/taskTypes'

const IN_PROGRESS_STATUSES = new Set<TaskRunStatus>([TaskRunStatus.QUEUED, TaskRunStatus.IN_PROGRESS])

// Compact "time ago" using a single largest unit, e.g. 18m, 1h, 7d.
export function compactTimeAgo(iso: string): string {
    const seconds = dayjs().diff(dayjs(iso), 'second')
    if (seconds < 60) {
        return 'now'
    }
    return humanFriendlyDuration(seconds, { maxUnits: 1 })
}

export function isTaskInProgress(task: Task): boolean {
    return task.latest_run ? IN_PROGRESS_STATUSES.has(task.latest_run.status) : false
}
