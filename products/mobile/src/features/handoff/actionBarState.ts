import { pullRequestKey } from '@/model/adapters/report'
import { POSTHOG_AGENT } from '@/model/agent'
import type { ActionBarLocalState, ActionBarState, PullRequestView, ReportView } from '@/model/types'
import { isTerminalRunStatus } from './runStream'

export function actionBarStateFor(report: ReportView, local: ActionBarLocalState = {}): ActionBarState {
    const pullRequests = new Map<string, PullRequestView>()
    for (const pr of [
        ...(report.work.pullRequests ?? []),
        ...(report.work.pullRequest ? [report.work.pullRequest] : []),
    ]) {
        const key = pullRequestKey(pr.url)
        if (!pullRequests.has(key)) {
            pullRequests.set(key, pr)
        }
    }
    const pending = report.task && !isTerminalRunStatus(report.task.status) ? report.task.pendingDecision : undefined
    const answered = pending !== undefined && local.answer?.questionId === pending.id
    const assignee = report.work.assignee
    const externallyClaimed = assignee && assignee.kind !== 'task'
    const task = externallyClaimed ? undefined : report.task
    let activity: ActionBarState['activity']
    if (assignee?.kind === 'agent' || assignee?.kind === 'system') {
        activity = { title: `Claimed by ${assignee.name}`, meta: 'Live activity unavailable', tone: 'idle' }
    } else if (task || local.handOffPending || assignee?.kind === 'task') {
        const actor = POSTHOG_AGENT.name
        if (task?.status === 'failed' || task?.status === 'cancelled') {
            activity = { title: `${actor} run ${task.status === 'failed' ? 'failed' : 'canceled'}`, tone: 'stopped' }
        } else if (task?.status === 'completed') {
            activity = { title: `${actor} finished this run`, tone: 'idle' }
        } else if (task?.connection === 'connecting') {
            activity = { title: `Connecting to ${actor}`, tone: 'idle' }
        } else if (task?.connection === 'reconnecting') {
            activity = { title: `Reconnecting to ${actor}`, tone: 'idle' }
        } else if (task?.connection === 'unavailable') {
            activity = { title: `${actor} activity unavailable`, tone: 'idle' }
        } else if (task?.status === 'queued' || task?.status === 'not_started' || local.handOffPending) {
            activity = { title: `${actor} ${task?.status === 'queued' ? 'queued' : 'starting'}`, tone: 'idle' }
        } else if (pending && !answered) {
            activity = { title: `${actor} waiting for your answer`, tone: 'idle' }
        } else if (task?.phase === 'working') {
            activity = { title: `${actor} is working`, meta: task.stage, tone: 'working' }
        } else if (task?.phase === 'idle') {
            activity = { title: `${actor} finished this turn`, tone: 'idle' }
        } else {
            activity = { title: `${actor} activity unavailable`, tone: 'idle' }
        }
    }
    return {
        pullRequests: [...pullRequests.values()],
        ...(activity ? { activity } : {}),
        ...(pending && !answered && !externallyClaimed ? { request: pending } : {}),
        ...(local.answer && (!pending || answered) && !externallyClaimed ? { answer: local.answer } : {}),
        showHandoff:
            report.work.state !== 'done' &&
            report.status !== 'resolved' &&
            report.canAct !== false &&
            !report.task &&
            !assignee &&
            !local.handOffPending &&
            pullRequests.size === 0,
    }
}
