"""Invented Self-driving inbox reports for the inbox consumer evals.

Every report is written for these evals, around the Hedgebox demo project. The seeder, the prompts and the
scorers import the same constants, so a title or a planted fact cannot drift between them.
"""

from __future__ import annotations

from typing import Literal

from posthog.dataclasses import frozen

ReportStatus = Literal["ready", "pending_input", "resolved", "suppressed"]
Actionability = Literal["immediately_actionable", "requires_human_input", "not_actionable"]
Priority = Literal["P0", "P1", "P2", "P3", "P4"]


@frozen
class InboxReport:
    key: str
    title: str
    summary: str
    status: ReportStatus = "ready"
    actionability: Actionability = "immediately_actionable"
    priority: Priority = "P2"
    for_user: bool = False
    """Names the case's user as a suggested reviewer, which puts an open report in their `for_you` view."""

    planted_fact: str = ""
    """Something only this report states. An answer that repeats it has read the report."""


CHECKOUT_TIMEOUT = InboxReport(
    key="checkout_timeout",
    title="Plan upgrades fail with a checkout timeout",
    summary=(
        "People who start a plan upgrade get `TimeoutError: Request timed out while creating checkout session` "
        "from `submitPayment` in `checkout.js`. The error tracking issue **Checkout API timeout** groups these "
        "exceptions.\n\n"
        "## Evidence\n"
        "- The exception has come back on several days over the last three weeks.\n"
        "- No session with the exception sends `upgraded_plan` afterwards, so each one is an upgrade that failed.\n\n"
        "## Likely cause\n"
        "The payment client gives up after 2 seconds, and creating a checkout session sometimes takes longer.\n\n"
        "## Suggested fix\n"
        "Raise the payment client timeout to 10 seconds and retry session creation once before showing an error."
    ),
    priority="P1",
    for_user=True,
    planted_fact="The payment client gives up after 2 seconds. The fix is a 10 second timeout and one retry.",
)

FIREFOX_UPLOAD_DROP = InboxReport(
    key="firefox_upload_drop",
    title="Fewer new Firefox users upload a first file",
    summary=(
        "The share of people who send `uploaded_file` within a day of `signed_up` fell for Firefox, and held "
        "steady for every other browser.\n\n"
        "## Evidence\n"
        "- The drop starts with the release that moved the upload button into the new file toolbar.\n"
        "- Firefox sessions show the toolbar rendered below the fold on the files page.\n\n"
        "## Suggested fix\n"
        "Pin the upload button to the top of the files page on Firefox until the toolbar layout is fixed."
    ),
    priority="P1",
    for_user=True,
    planted_fact="The upload button moved into a toolbar that Firefox renders below the fold. Pin it to the top.",
)

# The sandbox clones the Hedgebox app, and this is the report whose fix is in that code, so an agent can
# implement it and open a pull request.
UPLOAD_COUNTED_EARLY = InboxReport(
    key="upload_counted_early",
    title="Uploads are counted before they finish",
    summary=(
        "`uploaded_file` is sent when an upload starts, not when it finishes. `handleFileUpload` in "
        "`src/app/files/page.tsx` calls `posthog.capture('uploaded_file', ...)` before it waits for the upload, "
        "so an upload that a person abandons by leaving the page still counts.\n\n"
        "## Evidence\n"
        "- In `handleFileUpload`, the capture runs before the wait and before the new file is added to the list.\n"
        "- The activation funnel from `signed_up` to `uploaded_file` counts these unfinished uploads as "
        "activations.\n\n"
        "## Suggested fix\n"
        "Send `uploaded_file` after the new file is added to the list, so that the event marks a finished upload."
    ),
    priority="P2",
    for_user=True,
    planted_fact="`uploaded_file` is sent before the upload finishes. Send it after the new file is added.",
)

PDF_PREVIEW = InboxReport(
    key="pdf_preview",
    title="PDF previews fail to render for scanned documents",
    summary=(
        "Opening a preview throws `RenderError: Failed to render PDF preview`. The error tracking issue **File "
        "preview render failure** groups these exceptions.\n\n"
        "## Evidence\n"
        "- The failing files are image-only PDFs, which the preview worker tries to read as text.\n\n"
        "## Suggested fix\n"
        "Fall back to the image renderer when a PDF has no text layer."
    ),
    priority="P2",
    planted_fact="The failing files are image-only PDFs. Fall back to the image renderer.",
)

PRICING_PAGE_EXITS = InboxReport(
    key="pricing_page_exits",
    title="More visitors leave from the pricing page on mobile",
    summary=(
        "`$pageleave` on `/pricing/` rose for mobile visitors while desktop held steady.\n\n"
        "## Evidence\n"
        "- The plan comparison table needs horizontal scrolling on narrow screens.\n\n"
        "## Open question\n"
        "Whether to stack the plans or to shorten the table is a product decision."
    ),
    status="pending_input",
    actionability="requires_human_input",
    priority="P3",
)

WEEKLY_SIGNUPS_FLAT = InboxReport(
    key="weekly_signups_flat",
    title="Weekly signups are flat after the campaign ended",
    summary=(
        "`signed_up` volume returned to its level from before the sponsored campaign. Nothing is broken.\n\n"
        "## Evidence\n"
        "- Visits to `/mariustechtips/` stopped when the sponsorship ended."
    ),
    actionability="not_actionable",
    priority="P4",
)

LARGE_FILE_DOWNLOADS = InboxReport(
    key="large_file_downloads",
    title="Downloads of large files were slow last month",
    summary=(
        "`downloaded_file` for files over 1 GB took longer than usual for two weeks.\n\n"
        "## Resolution\n"
        "A change to the download chunk size fixed it."
    ),
    status="resolved",
    priority="P2",
)

DUPLICATE_BILLING_EMAILS = InboxReport(
    key="duplicate_billing_emails",
    title="Some accounts got two billing emails",
    summary=(
        "A few accounts on `business/standard` got the same billing email twice.\n\n"
        "## Evidence\n"
        "- The duplicates were sent by a test of the email provider and reached no customer."
    ),
    status="suppressed",
    actionability="not_actionable",
    priority="P4",
)

REPORTS: tuple[InboxReport, ...] = (
    CHECKOUT_TIMEOUT,
    FIREFOX_UPLOAD_DROP,
    UPLOAD_COUNTED_EARLY,
    PDF_PREVIEW,
    PRICING_PAGE_EXITS,
    WEEKLY_SIGNUPS_FLAT,
    LARGE_FILE_DOWNLOADS,
    DUPLICATE_BILLING_EMAILS,
)

FOR_USER_REPORTS: tuple[InboxReport, ...] = tuple(report for report in REPORTS if report.for_user)


def status_counts() -> dict[str, int]:
    """Reports in each status, as `system.inbox_reports` shows them. The table includes suppressed reports."""
    counts: dict[str, int] = {}
    for report in REPORTS:
        counts[report.status] = counts.get(report.status, 0) + 1
    return counts
