import { SignalReport, SignalReportArtefact } from '../../../types'
import { reportPullRequests } from '../../../utils/reportPullRequests'
import { ImplementationAgent } from '../implementationAgents'
import { ReportActionCard } from './ReportActionCard'
import { ReportExecuteFacts } from './ReportExecuteFacts'
import { ReportStageSectionTitle } from './ReportStageSectionTitle'

/** The work that fixes the problem: the proposed change, its pull request, and who and what is on it. */
export function ReportExecuteStage({
    report,
    artefacts,
    isClaimedByMe,
    onSendTo,
}: {
    report: SignalReport
    artefacts: SignalReportArtefact[]
    isClaimedByMe: boolean
    onSendTo: (agent: ImplementationAgent) => void
}): JSX.Element {
    const workStarted = reportPullRequests(report).length > 0 || !!report.implementation_in_flight

    return (
        <div className="flex flex-col gap-8">
            <section className="flex flex-col gap-3" aria-label="Implementation">
                <ReportStageSectionTitle>
                    {workStarted ? 'Implementation' : 'Recommended action'}
                </ReportStageSectionTitle>
                <ReportActionCard report={report} artefacts={artefacts} onSendTo={onSendTo} />
            </section>
            <section className="flex flex-col gap-1" aria-label="Details">
                <ReportStageSectionTitle>Details</ReportStageSectionTitle>
                <ReportExecuteFacts report={report} artefacts={artefacts} isClaimedByMe={isClaimedByMe} />
            </section>
        </div>
    )
}
