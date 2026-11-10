import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

import { contentAutopilotWeeklyReportLogic } from './contentAutopilotWeeklyReportLogic'
import { ContentAutopilotWeeklyReportPreview } from './ContentAutopilotWeeklyReportPreview'

export const ContentAutopilotWeeklyReportModal = (): JSX.Element => {
    const { weeklyReport, weeklyReportLoading, weeklyReportError, weeklyReportPreviewOpen } = useValues(
        contentAutopilotWeeklyReportLogic
    )
    const { closeWeeklyReportPreview, loadWeeklyReport, sendWeeklyReport } = useActions(
        contentAutopilotWeeklyReportLogic
    )

    let content: JSX.Element
    if (weeklyReportLoading || (!weeklyReport && !weeklyReportError)) {
        content = <LemonSkeleton className="h-64 w-full" />
    } else if (weeklyReportError || !weeklyReport) {
        content = (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadWeeklyReport, loading: weeklyReportLoading }}
            >
                Couldn't load the weekly report. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    } else if (weeklyReport.scorecard.answers === 0) {
        content = (
            <LemonBanner type="info">
                No answers to non-branded prompts were recorded in the last 7 complete days. A subscription skips a week
                like this and records why in its delivery history.
            </LemonBanner>
        )
    } else {
        content = <ContentAutopilotWeeklyReportPreview report={weeklyReport} />
    }

    return (
        <LemonModal
            isOpen={weeklyReportPreviewOpen}
            onClose={closeWeeklyReportPreview}
            title="Weekly AI visibility report"
            description="This is what a subscription sends each week to Slack or email."
            width={720}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeWeeklyReportPreview}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => sendWeeklyReport('preview')}
                        data-attr="content-autopilot-weekly-report-preview-send"
                    >
                        Send weekly report
                    </LemonButton>
                </>
            }
        >
            {content}
        </LemonModal>
    )
}
