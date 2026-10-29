// The PostHog run prompt follows `products/signals/frontend/inbox/inboxTaskKickoffLogic.ts`.
// The external handoff prompt also explains how an independent agent owns and updates its claim.

export interface PromptReport {
    id: string
    title?: string | null
    summary?: string | null
}

const REPORT_STATE_INSTRUCTIONS = `Keep the report's own state honest while you work, with the inbox MCP tools (\`inbox-reports-set-state\`, \`inbox-reports-claim\`):
- Read the report before you start. This run took the report when its task was created, but a rerun of a run that released it starts unclaimed: claim it again first, so the work you are about to do is visible to everyone else.
- Opening the PR is enough by itself. The PR is linked to the report for you, and merging it resolves the report. Do NOT set the state to resolved because you opened a PR: that closes the PR you just opened.
- If the work is finished without a PR, set the state to resolved with the reason that fits (\`fixed_outside_posthog\`, \`pr_merged\`, or \`already_fixed\`) and a short note that says what you did.
- If the report holds no work to do, set the state to suppressed with the reason that says why (\`report_unclear\`, \`analysis_wrong\`, \`wrong_repo\` with \`corrected_repository\`, \`wontfix_intentional\`, \`wontfix_irrelevant\`, or \`other\`) and a short note, then release your claim: suppressing does not release it for you.
- If you stop for any other reason, release your claim on the report, so it does not look like work is still in flight.`

export function buildCreatePrReportPrompt(report: PromptReport, feedback?: string): string {
    // The web reads `report.title ?? report.id`; an empty title counts as missing here too.
    const base = `Act on PostHog Inbox report "${report.title || report.id}" (id ${report.id}). Investigate the root cause using the report's contributing findings, implement the fix, and open a PR.${
        report.summary ? `\n\nReport summary:\n${report.summary}` : ''
    }\n\n${REPORT_STATE_INSTRUCTIONS}`
    const trimmed = feedback?.trim()
    if (!trimmed) {
        return base
    }
    return `${base}\n\nAdditional feedback from the user (take this into account):\n${trimmed}`
}

export function buildReportImplementationPrompt(report: PromptReport, reportUrl: string): string {
    return `Work on the PostHog Inbox report at ${reportUrl} (report ID: ${report.id}).

Use the PostHog MCP tools to retrieve the report and read its full work log with inbox-report-artefacts-list before changing code. Check its status, current assignee, and attached pull requests. If someone else has claimed it, ask me before taking over. If it is already resolved or suppressed, ask me before starting new work.

When you are ready to begin, claim the report with inbox-reports-claim. Keep the returned assignee.claim_id and pass it on subsequent claim updates and release calls. Verify the report's diagnosis against the current code, follow the repository's instructions, implement the smallest complete fix, and add focused regression coverage.

Open a pull request using the repository's conventions. Include ${reportUrl} in the pull request description, then call inbox-reports-claim again with the report ID, claim_id, and pull_requests (the array of all known PR URLs for this work) to attach it. Do not resolve the report when you open the pull request. PostHog resolves it when every linked PR is closed or merged and at least one merged. If PostHog cannot observe the merges, resolve it with inbox-reports-set-state after the fix lands.

If you stop without opening a pull request or completing the work, release the claim with inbox-reports-claim, claim_id, and release=true.`
}
