import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { SignalReport } from '../../types'
import { ReportPullRequestRef, prFilesUrl } from '../../utils/reportPresentation'

/** The "Open in GitHub" button, shared by the page toolbar and the summary's pull request note. */
export function OpenPullRequestButton({
    report,
    pullRequest,
}: {
    report: SignalReport
    pullRequest: ReportPullRequestRef
}): JSX.Element {
    return (
        <LemonButton
            type="primary"
            size="small"
            sideIcon={<IconExternal />}
            to={prFilesUrl(pullRequest.prUrl)}
            targetBlank
            tooltip={`${pullRequest.prRef.repoSlug}#${pullRequest.prRef.number}`}
            onClick={() => captureInboxReportAction({ report, actionType: 'open_pr', surface: 'detail_pane' })}
        >
            Open in GitHub
        </LemonButton>
    )
}
