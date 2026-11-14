import { ReactNode } from 'react'

import { SignalReport, SignalReportArtefact } from '../../../types'
import { reportPullRequests } from '../../../utils/reportPullRequests'
import { ReportActionCard } from './ReportActionCard'
import { ReportStageDetails } from './ReportStageDetails'
import { ReportStageSectionTitle } from './ReportStageSectionTitle'

/** The work that fixes the problem: the proposed change, its pull request, and who and what is on it. */
export function ReportExecuteStage({
    report,
    artefacts,
    note,
    children,
}: {
    report: SignalReport
    artefacts: SignalReportArtefact[]
    /** Shown inside the action card, under the proposed change. */
    note?: ReactNode
    /** The detail lines of this stage. */
    children?: ReactNode
}): JSX.Element {
    const workStarted = reportPullRequests(report).length > 0 || !!report.implementation_in_flight

    return (
        <div className="flex flex-col gap-8">
            <section className="flex flex-col gap-3" aria-label="Implementation">
                <ReportStageSectionTitle>
                    {workStarted ? 'Implementation' : 'Recommended action'}
                </ReportStageSectionTitle>
                <ReportActionCard report={report} artefacts={artefacts}>
                    {note}
                </ReportActionCard>
            </section>
            <ReportStageDetails>{children}</ReportStageDetails>
        </div>
    )
}
