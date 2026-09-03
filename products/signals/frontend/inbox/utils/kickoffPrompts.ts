import { SignalReport, SignalReportStatus } from '../types'
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

// The only statuses whose lifecycle still has work to do, and the only ones scout and pipeline
// reports reach after passing the safety judge. Everything else answers only: pre-judgment statuses
// (potential/candidate/in_progress) carry unjudged pipeline content, suppressed/failed reports carry
// the content the judge rejected, and a resolved report's persisted action suggestions would just
// redo already-completed work. Custom-agent reports are born ready without a judge pass - a
// deliberately trusted engineering surface, and the same trust autostart already extends by opening
// implementation PRs from them.
const ACTION_CAPABLE_STATUSES: readonly SignalReportStatus[] = [
    SignalReportStatus.READY,
    SignalReportStatus.PENDING_INPUT,
]

/** Whether Ask AI hands this report the action-capable framing rather than answer-only.
 * The Ask AI copy and suggestion rows key off this too, so the UI never invites an action the
 * wrapper would refuse. Beyond the status allowlist, an already-addressed report answers only:
 * a fix is already in flight, so acting on its recommendations would duplicate that work (the
 * same reason autostart and Create PR eligibility exclude it). A report the actionability judge
 * classified `not_actionable` answers only too — the product's own judgment says it holds no work
 * to act on (`canCreateImplementationPr` hides Create PR for the same reason), and resolving it
 * has its own button. A missing judgment stays action-capable: most such reports predate the
 * judge, and their stored prompts were still safety-judged. A report that already exposes an
 * implementation PR answers only, matching `canCreateImplementationPr`: acting on its stored
 * suggestions would open a second PR for the same work. */
export function isActionCapableReport(report: SignalReport): boolean {
    return (
        ACTION_CAPABLE_STATUSES.includes(report.status) &&
        report.already_addressed !== true &&
        report.actionability !== 'not_actionable' &&
        !report.implementation_pr_url
    )
}

/**
 * Prompt for a report's "Ask AI" run. The task is already linked to the report, but including the
 * URL lets the agent open and read the full report itself. The user's message follows after a blank
 * line for clear separation.
 *
 * `null` means the caller could not confirm the report's current state (the kickoff refetch
 * failed), which fails closed to answering.
 */
export function buildDiscussReportPrompt(report: SignalReport | null, reportUrl: string, question: string): string {
    if (report === null || !isActionCapableReport(report)) {
        return `Answer this question about the PostHog Inbox report at ${reportUrl}:\n\n${question.trim()}`
    }
    // Framed as question-or-action because a report's suggested prompts include next-step requests
    // ("create the alert the report recommends"); "answer this question" would pin the agent to
    // replying instead of acting.
    return `A user sent this about the PostHog Inbox report at ${reportUrl}. If it is a question, answer it; if it asks for action, carry the action out and summarize what you did:\n\n${question.trim()}`
}
