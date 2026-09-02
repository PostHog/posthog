import { SignalReport } from '../types'
import { reportAbsoluteUrl } from './inboxReportUrls'

/**
 * Prompt for a report's "Create PR" run.
 *
 * The reviewer of the resulting PR arrives with none of the context the report holds, so the report
 * link is the whole handoff — the same footer the autostarted implementation run is told to write
 * (`auto_start._build_autostart_task_description`). The report's local validation prompt is
 * deliberately left out: it may name internal hosts and tools, and this PR usually lands in a
 * public repository.
 */
export function buildCreatePrReportPrompt(report: SignalReport, feedback?: string): string {
    const reportUrl = reportAbsoluteUrl(report.id)
    const base = `Act on PostHog Inbox report "${report.title ?? report.id}" (id ${report.id}). Investigate the root cause using the report's contributing findings, implement the fix, and open a PR.${
        report.summary ? `\n\nReport summary:\n${report.summary}` : ''
    }\n\nWhen you open the PR, close the description with this footer so the reviewer can jump straight to the report: '*Created with [PostHog](https://posthog.com?ref=pr) from [this inbox report](${reportUrl}).*'`
    const trimmed = feedback?.trim()
    if (!trimmed) {
        return base
    }
    return `${base}\n\nAdditional feedback from the user (take this into account):\n${trimmed}`
}

/**
 * Prompt for a report's "Ask AI" run. The task is already linked to the report, but including the
 * URL lets the agent open and read the full report itself.
 */
export function buildDiscussReportPrompt(reportUrl: string, question: string): string {
    return `Answer this question about the PostHog Inbox report at ${reportUrl}:\n\n${question.trim()}`
}
