import type { SignalReport } from '../../types'

export function buildReportImplementationPrompt(report: SignalReport, reportUrl: string): string {
    return `Work on the PostHog Inbox report at ${reportUrl} (report ID: ${report.id}).

Use the PostHog MCP tools to retrieve the report and read its full work log with inbox-report-artefacts-list before changing code. Check its status, current assignee, and attached pull request. If someone else has claimed it, call that out before taking over.

When you are ready to begin, claim the report with inbox-reports-claim. Verify the report's diagnosis against the current code, follow the repository's instructions, implement the smallest complete fix, and add focused regression coverage.

Open a pull request using the repository's conventions. Include ${reportUrl} in the pull request description, then call inbox-reports-claim again with the report ID and pr_url to attach it. Do not resolve the report when you open the pull request. A connected pull request will resolve it when merged. If PostHog cannot observe the merge, resolve it with inbox-reports-set-state after it lands.

If you stop without opening a pull request or completing the work, release the claim with inbox-reports-claim and release=true.`
}
