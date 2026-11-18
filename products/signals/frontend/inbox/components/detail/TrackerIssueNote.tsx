import { IconWarning } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { SignalReport } from '../../types'
import { safeHttpUrl } from '../../utils/reportPresentation'

/**
 * The tracker issue behind a report's pull request, or why there is none.
 *
 * A team that cannot merge without a tracked work item has to find the pull requests that lack one
 * without reading logs, so the failure sits next to the pull request rather than in a state of its
 * own.
 */
export function TrackerIssueNote({ report }: { report: SignalReport }): JSX.Element | null {
    const issueUrl = safeHttpUrl(report.tracker_issue_url)

    if (issueUrl) {
        return (
            <span className="text-sm text-secondary">
                Tracked in <Link to={issueUrl}>{report.tracker_issue_reference ?? 'the issue tracker'}</Link>
            </span>
        )
    }

    if (report.tracker_issue_error) {
        return (
            <span className="text-sm text-warning flex items-center gap-1">
                <IconWarning />
                No tracker issue: {report.tracker_issue_error}
            </span>
        )
    }

    return null
}
