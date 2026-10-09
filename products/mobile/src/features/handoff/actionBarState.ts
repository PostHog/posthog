import type { ActionBarLocalState, ActionBarState, ReportView, TaskRunStatus } from '@/model/types'

const ACTIVE_RUN_STATUSES: ReadonlySet<TaskRunStatus> = new Set(['not_started', 'queued', 'in_progress'])

// Order matters. `pr_ready` wins over an answered question (`decided`), because the PR is what the answer led to.
export function actionBarStateFor(report: ReportView, local: ActionBarLocalState = {}): ActionBarState {
    if (report.work.state === 'done') {
        return 'resolved'
    }
    const pending = report.task?.pendingDecision
    const answered = pending !== undefined && local.answer?.questionId === pending.id
    if (pending && !answered) {
        return 'decision'
    }
    if (report.work.pullRequest?.state === 'open') {
        return 'pr_ready'
    }
    if (answered) {
        return 'decided'
    }
    const runActive = report.task !== undefined && ACTIVE_RUN_STATUSES.has(report.task.status)
    // A run that stopped can leave its claim behind; the run's own status is the fresher fact.
    const runStopped = report.task !== undefined && !runActive
    const agentClaimed =
        !runStopped &&
        report.work.state === 'working' &&
        (report.work.assignee?.kind === 'task' || report.work.assignee?.kind === 'agent')
    if (runActive || agentClaimed || local.handOffPending) {
        return 'handed'
    }
    return 'idle'
}
