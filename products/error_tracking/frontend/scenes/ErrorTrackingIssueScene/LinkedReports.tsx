import { useValues } from 'kea'

import { SignalReportEntry } from 'lib/signals/SignalReportEntry'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'

/**
 * Reports the inbox grouped this issue's signals into, most recently updated first.
 *
 * The same entry the ticket thread shows, so a self-driving investigation reads identically wherever
 * someone meets it. It has no private-note lock here, because an error page has no customer-facing
 * thread for the lock to distinguish it from.
 */
export function LinkedReportsList({ reports }: { reports: SignalReportApi[] }): JSX.Element | null {
    if (reports.length === 0) {
        return null
    }
    return (
        <div className="shrink-0 border-b px-4 py-3">
            {/* Capped, so the title and the fix state stay as close together as they are in the ticket
                thread. Left aligned rather than centred, to sit under the issue title above it. */}
            <div className="flex flex-col gap-3 max-w-3xl">
                {reports.map((report) => (
                    <SignalReportEntry key={report.id} report={report} agentSubject="errors" />
                ))}
            </div>
        </div>
    )
}

/**
 * Sits between the issue header and the two columns, so it is visible without a click.
 *
 * Renders nothing when the inbox never investigated this issue, which is the common case, and so leaves
 * that page exactly as it was.
 */
export function LinkedReports(): JSX.Element | null {
    const { linkedReports } = useValues(errorTrackingIssueSceneLogic)
    return <LinkedReportsList reports={linkedReports} />
}
