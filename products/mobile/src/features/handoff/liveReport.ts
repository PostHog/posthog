import { pullRequestKey, pullRequestNumber } from '@/model/adapters/report'
import type { DecisionQuestion, PullRequestView, ReportView } from '@/model/types'

import type { ReportHandoff, StoredAnswer } from './handoffStore'
import { decisionQuestionFor } from './permissionRequest'
import { displayStage, isTerminalRunStatus } from './runStream'
import type { LiveTaskRunView, RunStreamState, RunTarget } from './types'

export function runTarget(report: ReportView | undefined, entry: ReportHandoff | undefined): RunTarget | undefined {
    const assignee = report?.work.assignee
    if (assignee && assignee.kind !== 'task') {
        return undefined
    }
    if (!assignee && entry?.started && entry.started.taskId !== report?.task?.taskId) {
        return entry.started
    }
    const taskId = assignee?.taskId ?? report?.task?.taskId
    if (taskId) {
        if (report?.task?.taskId === taskId) {
            return { taskId, runId: report.task.runId }
        }
        return entry?.started?.taskId === taskId ? entry.started : { taskId }
    }
    return entry?.started
}

export function currentDecision(entry: ReportHandoff | undefined): DecisionQuestion | undefined {
    const live = entry?.live
    if (!live?.pending || isTerminalRunStatus(live.status)) {
        return undefined
    }
    const answered = entry?.partial?.requestId === live.pending.record.requestId ? entry.partial.labels : []
    return decisionQuestionFor(live.pending, answered)
}

// Once the agent took the answer, it stays until the run shows new activity, so the decided card does not flash.
export function visibleAnswer(
    entry: ReportHandoff | undefined,
    current: DecisionQuestion | undefined
): StoredAnswer | undefined {
    const answer = entry?.answer
    if (!answer || !entry?.live) {
        return undefined
    }
    if (current) {
        return current.id === answer.questionId ? answer : undefined
    }
    if (answer.delivery === 'sending') {
        return answer
    }
    return entry.live.activity === answer.activity ? answer : undefined
}

export function pullRequestFromUrl(url: string): PullRequestView {
    const number = pullRequestNumber(url)
    return { url, state: 'unknown', ...(number ? { number } : {}) }
}

function liveTask(live: RunStreamState): LiveTaskRunView {
    const stage = displayStage(live)
    return {
        taskId: live.taskId,
        runId: live.runId,
        status: live.status,
        phase: live.turnEnded ? 'idle' : (live.phase ?? 'unknown'),
        ...(live.connection ? { connection: live.connection } : {}),
        ...(stage ? { stage } : {}),
        ...(live.errorMessage ? { errorMessage: live.errorMessage } : {}),
    }
}

// The report's own data wins where it knows more, for example a PR's review state.
export function mergeLiveRun(report: ReportView, entry: ReportHandoff | undefined): ReportView {
    const target = runTarget(report, entry)
    const live =
        entry?.live && target?.taskId === entry.live.taskId && (!target.runId || target.runId === entry.live.runId)
            ? entry.live
            : undefined
    let task = target?.taskId === report.task?.taskId ? report.task : undefined
    if (live) {
        const settledLive =
            task && isTerminalRunStatus(task.status) ? { ...live, status: task.status, phase: 'idle' as const } : live
        task = liveTask(settledLive)
    } else if (target && !task) {
        task = { taskId: target.taskId, runId: target.runId, status: 'queued', phase: 'unknown' }
    }
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
    for (const url of [...(live?.prUrls ?? []), ...(live?.prUrl ? [live.prUrl] : [])]) {
        const key = pullRequestKey(url)
        if (!pullRequests.has(key)) {
            pullRequests.set(key, pullRequestFromUrl(url))
        }
    }
    const allPullRequests = [...pullRequests.values()]
    const pullRequest = report.work.pullRequest ?? allPullRequests[0]
    if (task && live) {
        const pendingDecision = isTerminalRunStatus(task.status) ? undefined : currentDecision(entry)
        task = { ...task, pendingDecision }
    }
    return {
        ...report,
        work: { ...report.work, pullRequests: allPullRequests, pullRequest },
        task,
    }
}

function sameLive(a: RunStreamState | undefined, b: RunStreamState | undefined): boolean {
    if (a === b) {
        return true
    }
    if (!a || !b) {
        return false
    }
    return (
        a.taskId === b.taskId &&
        a.runId === b.runId &&
        a.status === b.status &&
        a.phase === b.phase &&
        a.connection === b.connection &&
        displayStage(a) === displayStage(b) &&
        a.pending === b.pending &&
        a.prUrl === b.prUrl &&
        a.prUrls.length === b.prUrls.length &&
        a.prUrls.every((url, index) => url === b.prUrls[index]) &&
        a.errorMessage === b.errorMessage &&
        a.turnEnded === b.turnEnded &&
        a.activity === b.activity
    )
}

// Message chunks stream many times a second and would otherwise re-render the whole screen for each one.
export function sameVisibleEntry(a: ReportHandoff | undefined, b: ReportHandoff | undefined): boolean {
    if (a === b) {
        return true
    }
    if (!a || !b) {
        return false
    }
    return (
        a.started === b.started &&
        a.unstartedTaskId === b.unstartedTaskId &&
        a.partial === b.partial &&
        a.answer === b.answer &&
        a.notice === b.notice &&
        sameLive(a.live, b.live)
    )
}
