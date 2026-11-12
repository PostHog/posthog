import { useActions, useValues } from 'kea'

import { IconClock } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { canMonitorReport } from '../../utils/reportActions'

export function ReportStartMonitoringPrompt({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { reportStateSaving } = useValues(logic)
    const { changeReportState } = useActions(logic)

    // Follow-up checks renders this only once the report has at least one check.
    if (!canMonitorReport(report, true)) {
        return null
    }

    return (
        <div className="@container">
            <div className="flex flex-col gap-2 rounded border bg-surface-secondary px-3 py-2 @[22rem]:flex-row @[22rem]:items-center @[22rem]:justify-between">
                <span className="text-sm text-secondary">Fix already implemented?</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconClock />}
                    loading={reportStateSaving}
                    onClick={() => {
                        captureInboxReportAction({ report, actionType: 'monitor', surface: 'detail_pane' })
                        changeReportState('monitoring')
                    }}
                    tooltip="PostHog watches to make sure the fix works"
                    className="self-start @[22rem]:self-auto"
                    data-attr="inbox-report-start-monitoring"
                >
                    Start monitoring now
                </LemonButton>
            </div>
        </div>
    )
}
