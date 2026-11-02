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
    const run = task.latest_run
    if (!run || !IN_PROGRESS_STATUSES.has(run.status)) {
        return false
    }
    // An interactive run stays `in_progress` between turns, so that status alone does not mean the agent works.
    return !(run.status === TaskRunStatus.IN_PROGRESS && run.state?.mode === 'interactive')
}
