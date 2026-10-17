import type { ImplementationSlotClaim, ReportTaskEntry } from '../logics/inboxReportDetailLogic'
import type { SignalReport } from '../types'
import { parsePrUrlParts } from './reportPresentation'
import { reportPullRequests } from './reportPullRequests'

export type ReportNextStep =
    | { kind: 'review'; url: string; label: string; reason: string }
    | { kind: 'task'; taskId: string; runId: string; reason: string }
    | { kind: 'implement' | 'investigate' | 'wait' | 'load'; reason: string }
    | { kind: 'none' }

export function reportNextStep(
    report: SignalReport,
    tasks: ReportTaskEntry[] | null,
    slotClaim: ImplementationSlotClaim | null,
    selectedPrUrl?: string
): ReportNextStep {
    if (report.status === 'resolved' || report.status === 'suppressed') {
        return { kind: 'none' }
    }
    const openPrs = reportPullRequests(report).filter(
        (pr) => !pr.merged && pr.state !== 'merged' && pr.state !== 'closed' && parsePrUrlParts(pr.url)
    )
    const openPr = openPrs.find((pr) => pr.url === selectedPrUrl) ?? openPrs[0]
    if (openPr) {
        return {
            kind: 'review',
            url: openPr.url,
            label: openPr.state === 'draft' ? 'Review draft PR' : 'Review PR',
            reason:
                openPr.review_decision === 'changes_requested'
                    ? 'A reviewer requested changes. Review the PR and continue its task.'
                    : 'A pull request is ready to inspect. Check its changes and CI results.',
        }
    }
    const runningTask = [...(tasks ?? [])]
        .sort((a, b) => new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime())
        .find(
            (entry) =>
                entry.task.latest_run && !['completed', 'failed', 'cancelled'].includes(entry.task.latest_run.status)
        )
    if (runningTask?.task.latest_run) {
        return {
            kind: 'task',
            taskId: runningTask.task.id,
            runId: runningTask.task.latest_run.id,
            reason: 'Work is already running. Open the task to follow it or add instructions.',
        }
    }
    if (reportPullRequests(report).some((pr) => pr.merged || pr.state === 'merged')) {
        return { kind: 'wait', reason: 'The fix is merged. Check that it is live before resolving the report.' }
    }
    if (report.already_addressed) {
        return { kind: 'wait', reason: 'A fix is already in progress. Check the report before resolving it.' }
    }
    if (report.assignee || slotClaim) {
        return { kind: 'wait', reason: 'This report is already claimed. Check its runs before starting more work.' }
    }
    if (!['ready', 'pending_input', 'failed'].includes(report.status)) {
        return { kind: 'wait', reason: 'The report is still being prepared.' }
    }
    if (report.actionability === 'not_actionable') {
        return { kind: 'none' }
    }
    if (tasks === null) {
        return { kind: 'load', reason: 'Load the report’s runs before starting work.' }
    }
    if (
        report.status === 'ready' &&
        report.actionability === 'immediately_actionable' &&
        reportPullRequests(report).length === 0
    ) {
        return { kind: 'implement', reason: 'The report is ready for implementation.' }
    }
    return { kind: 'investigate', reason: 'Check the evidence and identify any input needed before implementation.' }
}

export function reportInvestigationPrompt(reportId: string, reportUrl: string): string {
    return `Investigate the PostHog Inbox report at ${reportUrl} (report ID: ${reportId}).
Read the report and its full work log with the PostHog MCP tools. Check the evidence against current data and code.
Explain whether the problem is real, its cause, its impact, and the smallest useful next step.
If a decision needs human input, explain the options and ask for that input.
Do not change code, open a pull request, or change the report's state.`
}
