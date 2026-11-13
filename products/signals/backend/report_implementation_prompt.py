from uuid import UUID

from posthog.utils import absolute_uri


def build_report_implementation_prompt(team_id: int, report_id: str | UUID) -> str:
    # The web inbox copies the same text from buildReportImplementationPrompt.ts. Change the two together.
    report_url = absolute_uri(f"/project/{team_id}/inbox/reports/{report_id}")
    return f"""Work on the PostHog Inbox report at {report_url} (report ID: {report_id}).

Use the PostHog MCP tools to retrieve the report and read its full work log with inbox-report-artefacts-list before changing code. Check its status, current assignee, and attached pull request. If someone else has claimed it, call that out before taking over.

When you are ready to begin, claim the report with inbox-reports-claim. Verify the report's diagnosis against the current code, follow the repository's instructions, implement the smallest complete fix, and add focused regression coverage.

Open a pull request using the repository's conventions. Include {report_url} in the pull request description, then call inbox-reports-claim again with the report ID and pr_url to attach it. Do not resolve the report when you open the pull request. A connected pull request will resolve it when merged. If PostHog cannot observe the merge, resolve it with inbox-reports-set-state after it lands.

If you stop without opening a pull request or completing the work, release the claim with inbox-reports-claim and release=true."""
