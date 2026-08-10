import { useValues } from 'kea'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { SignalReportFixOrStatus } from 'lib/signals/SignalReportFixOrStatus'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

/**
 * One report, as a row in the issue's side panel.
 *
 * Carries the same AI-colored left edge as the report entry on a support ticket, so the two places
 * a self-driving investigation surfaces read as the same actor. The edge is a pseudo-element so it
 * can run the full height without fighting the border radius the way a left border does.
 */
function LinkedReportRow({ report }: { report: SignalReportApi }): JSX.Element {
    return (
        <div className="relative overflow-hidden rounded border border-primary bg-surface-primary transition-colors hover:border-secondary py-1.5 pl-3 pr-2 after:content-[''] after:absolute after:inset-y-0 after:left-0 after:w-1 after:bg-ai">
            {/* The report is the target, and the pull request inside `SignalReportFixOrStatus` is its
                own: an anchor can't contain another, so the state stays a sibling of the link. */}
            <Link
                to={urls.inboxReport('reports', report.id)}
                className="block text-sm font-semibold leading-snug text-inherit no-underline hover:text-inherit"
            >
                {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
            </Link>
            <div className="mt-1">
                <SignalReportFixOrStatus report={report} />
            </div>
        </div>
    )
}

/**
 * Reports the inbox grouped this issue's signals into, most recently updated first.
 *
 * Renders nothing at all when there are none, which is the common case: an issue nobody investigated
 * should not carry an empty section, and there's no skeleton either, because a placeholder on every
 * issue page costs more than it tells anyone.
 */
export function LinkedReportsSection({ reports }: { reports: SignalReportApi[] }): JSX.Element | null {
    if (reports.length === 0) {
        return null
    }

    return (
        <ScenePanelLabel
            title={
                // Plain text like the panel's other section labels. The agent identity is carried by
                // the AI-colored edge on each row, so a logo here would only add noise.
                <Tooltip title="A PostHog agent that investigates errors against your codebase. Not a teammate.">
                    <span>Self-driving</span>
                </Tooltip>
            }
        >
            <div className="flex flex-col gap-1.5">
                {reports.map((report) => (
                    <LinkedReportRow key={report.id} report={report} />
                ))}
            </div>
        </ScenePanelLabel>
    )
}

export function LinkedReports(): JSX.Element | null {
    const { linkedReports } = useValues(errorTrackingIssueSceneLogic)
    return <LinkedReportsSection reports={linkedReports} />
}
