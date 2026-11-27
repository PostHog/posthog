import { useActions, useValues } from 'kea'

import { LemonBadge, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { SignalReportFixOrStatus } from 'lib/signals/SignalReportFixOrStatus'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'
import {
    deriveHeadline,
    displayConventionalCommitTitle,
} from 'products/signals/frontend/inbox/utils/reportPresentation'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { IssuePaneSectionHeader } from './IssuePaneSectionHeader'
import { issuePaneSectionsLogic } from './issuePaneSectionsLogic'

/**
 * One report, as a row of the right pane.
 *
 * The link takes the whole left column so the row reads as one target, and the fix state stays a
 * sibling of it: an anchor cannot contain another, and a click on the pull request has to open the
 * pull request.
 */
function LinkedReportRow({ report }: { report: SignalReportApi }): JSX.Element {
    const headline = deriveHeadline(report.summary)
    return (
        <div className="flex items-start justify-between gap-2 px-2 py-1.5 border-b transition-colors hover:bg-surface-secondary">
            <Link
                to={urls.inboxReport('reports', report.id)}
                className="block min-w-0 flex-1 text-inherit no-underline hover:text-inherit"
            >
                <div className="text-sm font-semibold leading-snug">
                    {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
                </div>
                {/* When the report was last worked on matters as much as what it says, and the two fit on
                    one line at this width. */}
                <p className="mt-0.5 mb-0 text-xs text-muted leading-snug">
                    <TZLabel time={report.updated_at} />
                    {headline ? ` · ${headline}` : ''}
                </p>
            </Link>
            <div className="shrink-0">
                <SignalReportFixOrStatus report={report} />
            </div>
        </div>
    )
}

export interface LinkedReportsSectionProps {
    reports: SignalReportApi[]
    open: boolean
    onToggle: () => void
}

/**
 * Reports the inbox grouped this issue's signals into, most recently updated first.
 *
 * This is a section of the right pane, not a card sitting on top of one, so it wears the pane's own
 * chrome: square corners, no outer border, and rows that run the full width.
 *
 * The section never takes more than half the pane. An issue the agent looked at many times would
 * otherwise push the exception card, and with it the stack trace, off the bottom of the pane.
 */
export function LinkedReportsSection({ reports, open, onToggle }: LinkedReportsSectionProps): JSX.Element | null {
    if (reports.length === 0) {
        return null
    }
    return (
        // The pane paints no background of its own on desktop, so this section paints the same one the
        // exception card below it paints. Without it the rows show the page behind the pane.
        <div className="min-h-0 max-h-[50%] flex flex-col bg-surface-primary">
            <IssuePaneSectionHeader
                name="Self-driving"
                open={open}
                onToggle={onToggle}
                preview={<LemonBadge.Number count={reports.length} status="muted" size="small" maxDigits={2} />}
                dataAttr="error-tracking-issue-reports-toggle"
                trailing={
                    <Tooltip title="A PostHog agent that investigates errors against your codebase. Not a teammate.">
                        <span className="shrink-0 text-xs text-muted-alt">PostHog agent</span>
                    </Tooltip>
                }
            />
            {/* The header stays put while the rows scroll, so the section keeps its name once the list
                is longer than the space it has. */}
            {open ? (
                <div className="min-h-0 overflow-y-auto">
                    {reports.map((report) => (
                        <LinkedReportRow key={report.id} report={report} />
                    ))}
                </div>
            ) : null}
        </div>
    )
}

/** Renders nothing when the inbox never investigated this issue, which is the common case. */
export function LinkedReports(): JSX.Element | null {
    const { linkedReports } = useValues(errorTrackingIssueSceneLogic)
    const { reportsOpen } = useValues(issuePaneSectionsLogic)
    const { setReportsOpen } = useActions(issuePaneSectionsLogic)
    return (
        <LinkedReportsSection
            reports={linkedReports}
            open={reportsOpen}
            onToggle={() => setReportsOpen(!reportsOpen)}
        />
    )
}
