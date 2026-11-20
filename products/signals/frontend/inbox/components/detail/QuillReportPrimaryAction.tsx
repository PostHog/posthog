import { useValues } from 'kea'

import { startDisabledReason, todayNextStep } from 'scenes/project-homepage/today/todayNextStep'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'
import { TodayReportPrimaryAction } from 'scenes/project-homepage/today/TodayReportPrimaryAction'

import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'

/** The one primary action of the report. It follows the state of the work, not the stage in view. */
export function QuillReportPrimaryAction({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportTaskToOpen, implementationSlotClaim } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const { createPrDisabledReason, aiConsentDisabledReason } = useValues(inboxTaskKickoffLogic)
    const { reportState, reportUrl, isSample, page } = useValues(todayReportLogic({ reportId: report.id }))
    const task = reportTaskToOpen?.task
    const { primary, taskPickedUp } = todayNextStep(report, {
        namedPullRequest: page?.named_pull_request ?? null,
        solutionNamesPullRequest: page?.solution_names_pull_request ?? false,
        slotClaimed: implementationSlotClaim !== null,
        runningTask: task?.latest_run ? { taskId: task.id, runId: task.latest_run.id } : null,
    })

    if (reportState !== 'open' || !primary) {
        return null
    }

    return (
        <TodayReportPrimaryAction
            primary={primary}
            report={report}
            reportUrl={reportUrl}
            isSample={isSample}
            startReason={startDisabledReason(report, taskPickedUp, {
                createPrDisabledReason,
                aiConsentDisabledReason,
            })}
            surface="detail_pane"
        />
    )
}
