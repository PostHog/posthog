import { IconArrowRight, IconCheckCircle, IconHide, IconPullRequest } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SignalReport, SignalReportStatus } from '../../../types'
import { safeHttpUrl } from '../../../utils/reportPresentation'
import { primaryReportPullRequest, reportPullRequests } from '../../../utils/reportPullRequests'
import { currentReportStage } from './reportStages'

export interface ReportStageActionHandlers {
    onImplement: () => void
    onDismiss: () => void
    onResolve: () => void
}

/**
 * The actions beside the stage switch. They follow the stage the report has reached, not the tab in view:
 * one primary step when the report waits on a person, and none while it waits on a check.
 */
export function ReportStageActions({
    report,
    handlers,
}: {
    report: SignalReport
    handlers: ReportStageActionHandlers
}): JSX.Element {
    const stage = currentReportStage(report)
    const pullRequest = reportPullRequests(report).length > 0 ? primaryReportPullRequest(report) : null
    const pullRequestUrl = safeHttpUrl(pullRequest?.url)
    const awaitsReview = pullRequest?.state === 'open' || pullRequest?.state === 'draft'
    const terminal = report.status === SignalReportStatus.RESOLVED || report.status === SignalReportStatus.CLOSED

    return (
        <div className="flex flex-wrap items-center gap-2">
            {stage === 'measure' && !terminal && (
                <Button
                    variant="outline"
                    onClick={handlers.onResolve}
                    tooltip="Resolve now, without waiting for the follow-up checks"
                    data-attr="inbox-report-stage-resolve"
                >
                    <IconCheckCircle />
                    Resolve
                </Button>
            )}
            {stage !== 'measure' && (
                <Button variant="outline" onClick={handlers.onDismiss} data-attr="inbox-report-stage-dismiss">
                    <IconHide />
                    Dismiss
                </Button>
            )}
            {stage === 'spec' && (
                <Button variant="primary" onClick={handlers.onImplement} data-attr="inbox-report-stage-implement">
                    Implement
                    <IconArrowRight />
                </Button>
            )}
            {stage === 'execute' && awaitsReview && pullRequestUrl && (
                <Button
                    variant="primary"
                    render={<LinkPrimitive to={pullRequestUrl} target="_blank" />}
                    data-attr="inbox-report-stage-review-pr"
                >
                    <IconPullRequest />
                    Review pull request
                </Button>
            )}
        </div>
    )
}
