import { pullRequestNumber } from '@/model/adapters/report'
import type { DecisionQuestion, PullRequestView, ReportView } from '@/model/types'

import type { ReportHandoff, StoredAnswer } from './handoffStore'
import { decisionQuestionFor } from './permissionRequest'
import { displayStage, isTerminalRunStatus } from './runStream'
import type { LiveTaskRunView, RunStreamState, RunTarget } from './types'

const REPLY_PREFIX = 'reply:'

export function runTarget(report: ReportView | undefined, entry: ReportHandoff | undefined): RunTarget | undefined {
    if (entry?.started) {
        return entry.started
    }
    return report?.task ? { taskId: report.task.taskId, runId: report.task.runId } : undefined
}

/** A decision card with no options takes a typed reply, sent as a message instead of an answer. */
export function isReplyPrompt(question: DecisionQuestion): boolean {
    return question.id.startsWith(REPLY_PREFIX)
}

export function currentDecision(entry: ReportHandoff | undefined, hasOpenPr: boolean): DecisionQuestion | undefined {
    const live = entry?.live
    if (!live) {
        return undefined
    }
    if (live.pending) {
        const answered = entry?.partial?.requestId === live.pending.record.requestId ? entry.partial.labels : []
        return decisionQuestionFor(live.pending, answered)
    }
    if (!live.turnEnded || hasOpenPr || isTerminalRunStatus(live.status) || !live.lastMessage) {
        return undefined
    }
    return { id: `${REPLY_PREFIX}${live.runId}:${live.activity}`, question: live.lastMessage.trim(), options: [] }
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

function pullRequestFromUrl(url: string): PullRequestView {
    const number = pullRequestNumber(url)
    return { url, state: 'open', ...(number ? { number } : {}) }
}

function liveTask(report: ReportView, live: RunStreamState): LiveTaskRunView {
    const stage = displayStage(live) ?? report.task?.stage
    return {
        taskId: live.taskId,
        runId: live.runId,
        status: live.status,
        ...(stage ? { stage } : {}),
        ...(live.errorMessage ? { errorMessage: live.errorMessage } : {}),
    }
}

// The report's own data wins where it knows more, for example a PR's review state.
export function mergeLiveRun(report: ReportView, entry: ReportHandoff | undefined): ReportView {
    const target = runTarget(report, entry)
    const live = entry?.live && target?.taskId === entry.live.taskId ? entry.live : undefined
    let task = report.task
    if (live) {
        task = liveTask(report, live)
    } else if (entry?.started && report.task?.taskId !== entry.started.taskId) {
        // Created on this device a moment ago; the report and the stream have not caught up yet.
        task = { taskId: entry.started.taskId, runId: entry.started.runId, status: 'queued' }
    }
    let pullRequest = report.work.pullRequest
    if (live?.prUrl && pullRequest?.url !== live.prUrl) {
        pullRequest = pullRequestFromUrl(live.prUrl)
    }
    if (task && live) {
        const current = currentDecision(entry, pullRequest?.state === 'open')
        const pendingDecision = current ?? visibleAnswer(entry, current)?.question
        task = { ...task, ...(pendingDecision ? { pendingDecision } : {}) }
    }
    return {
        ...report,
        work: { ...report.work, ...(pullRequest ? { pullRequest } : {}) },
        ...(task ? { task } : {}),
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
        displayStage(a) === displayStage(b) &&
        a.pending === b.pending &&
        a.prUrl === b.prUrl &&
        a.errorMessage === b.errorMessage &&
        a.turnEnded === b.turnEnded &&
        a.activity === b.activity &&
        // The message only shows on the reply card, after the turn ended.
        (!a.turnEnded || a.lastMessage === b.lastMessage)
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
        a.partial === b.partial &&
        a.answer === b.answer &&
        a.notice === b.notice &&
        sameLive(a.live, b.live)
    )
}
