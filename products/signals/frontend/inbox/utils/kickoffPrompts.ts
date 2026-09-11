import { SignalReport, SignalReportStatus } from '../types'
import { reportAbsoluteUrl } from './inboxReportUrls'

// The report's state is part of what a run owes the reader, and only the two ends of the happy
// path are automatic: creating an implementation task claims the report server-side
// (`record_implementation_task`), and a merged PR resolves it (`_apply_pr_report_state`). Every
// other ending needs the agent, so spell the endings out. Resolving through the state API also
// closes the report's open PR (`close_pr_when_report_dismissed`), which is why opening a PR must
// not be reported as a resolution. Without this the report stays claimed and unresolved after a
// run that found nothing to do, and the next reader cannot tell it from work still in flight.
// The claim needs the same care from both ends: it is taken once, when the task is created, so a
// rerun of a task that released it starts unclaimed, and suppressing a report leaves the claim
// standing (only `claim_report` clears an actor), which would show a finished run as still working
// if the report is ever restored.
const REPORT_STATE_INSTRUCTIONS = `Keep the report's own state honest while you work, with the inbox MCP tools (\`inbox-reports-set-state\`, \`inbox-reports-claim\`):
- Read the report before you start. This run took the report when its task was created, but a rerun of a run that released it starts unclaimed: claim it again first, so the work you are about to do is visible to everyone else.
- Opening the PR is enough by itself. The PR is linked to the report for you, and merging it resolves the report. Do NOT set the state to resolved because you opened a PR: that closes the PR you just opened.
- If the work is finished without a PR, set the state to resolved with the reason that fits (\`fixed_outside_posthog\`, \`pr_merged\`, or \`already_fixed\`) and a short note that says what you did.
- If the report holds no work to do, set the state to suppressed with the reason that says why (\`report_unclear\`, \`analysis_wrong\`, \`wrong_repo\` with \`corrected_repository\`, \`wontfix_intentional\`, \`wontfix_irrelevant\`, or \`other\`) and a short note, then release your claim: suppressing does not release it for you.
- If you stop for any other reason, release your claim on the report, so it does not look like work is still in flight.`

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
    }\n\nWhen you open the PR, close the description with this footer so the reviewer can jump straight to the report: '*Created with [PostHog](https://posthog.com?ref=pr) from [this inbox report](${reportUrl}).*'\n\n${REPORT_STATE_INSTRUCTIONS}`
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
    // State hygiene rides along with the action framing only: a run that just answers a question
    // has changed nothing about the report, so the only endings worth recording are an action that
    // finishes the report or an exchange that shows it holds no work. A discussion run may open a
    // PR of its own, so it needs the same do-not-resolve-on-an-open-PR rule the Create PR prompt
    // carries. It also never claims the report (`record_report_task` claims for `implementation`
    // only) and the state API has no ownership precondition, so it is told to keep its hands off a
    // report somebody else is working — the check a discussion run can actually make.
    return `A user sent this about the PostHog Inbox report at ${reportUrl}. If it is a question, answer it; if it asks for action, carry the action out and summarize what you did:\n\n${question.trim()}\n\nIf you carry an action out that finishes what the report asked for, record it on the report with the inbox MCP tools (\`inbox-reports-set-state\`): set the state to resolved with the reason \`fixed_outside_posthog\` and a short note that says what you did. Opening a pull request does not finish it — the PR is linked to the report and merging it resolves the report, so setting the state to resolved would close the PR you just opened. If the exchange shows the report holds no work to do, set the state to suppressed with the reason that says why and a short note. Before either, read the report again and leave its state alone when somebody else holds it or an implementation PR is already open on it: that work is not yours to end. Answering a question changes nothing about the report, so leave its state alone.`
}
