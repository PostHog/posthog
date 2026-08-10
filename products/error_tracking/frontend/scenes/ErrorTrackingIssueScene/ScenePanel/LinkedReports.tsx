import { useValues } from 'kea'

import { Link, Tooltip } from '@posthog/lemon-ui'

import { SignalReportCard } from 'lib/signals/SignalReportCard'
import { SignalReportFixOrStatus } from 'lib/signals/SignalReportFixOrStatus'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { errorTrackingIssueSceneLogic } from '../errorTrackingIssueSceneLogic'

/** One report, stacked rather than side by side, because the panel column is 300px wide. */
function LinkedReportRow({ report }: { report: SignalReportApi }): JSX.Element {
    return (
        <SignalReportCard className="py-1.5 pl-3 pr-2">
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
        </SignalReportCard>
    )
}

/** No section at all when the inbox never investigated this issue, which is the common case. */
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
