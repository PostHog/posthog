import { SignalReport, SignalReportStatus } from '../../../types'
import { reportPullRequests } from '../../../utils/reportPullRequests'

/** The three stages a report moves through: what is wrong, the work that fixes it, and whether the fix held. */
export type ReportStage = 'spec' | 'execute' | 'measure'

export type ReportStageProgress = 'done' | 'current' | 'upcoming'

export const REPORT_STAGES: readonly ReportStage[] = ['spec', 'execute', 'measure']

export const REPORT_STAGE_LABEL: Record<ReportStage, string> = {
    spec: 'Spec',
    execute: 'Execute',
    measure: 'Measure',
}

const MEASURE_STATUSES: SignalReportStatus[] = [
    SignalReportStatus.MONITORING,
    SignalReportStatus.RESOLVED,
    SignalReportStatus.CLOSED,
]

type StagedReport = Pick<
    SignalReport,
    | 'status'
    | 'assignee'
    | 'implementation_in_flight'
    | 'pull_requests'
    | 'implementation_pr_url'
    | 'implementation_pr_state'
    | 'implementation_pr_merged'
>

/** The stage the report's work has reached. A report opens on this stage. */
export function currentReportStage(report: StagedReport): ReportStage {
    if (MEASURE_STATUSES.includes(report.status)) {
        return 'measure'
    }
    if (reportPullRequests(report).length > 0 || report.implementation_in_flight || report.assignee) {
        return 'execute'
    }
    return 'spec'
}

export function reportStageProgress(stage: ReportStage, report: StagedReport): ReportStageProgress {
    if (report.status === SignalReportStatus.RESOLVED) {
        return 'done'
    }
    const distance = REPORT_STAGES.indexOf(stage) - REPORT_STAGES.indexOf(currentReportStage(report))
    return distance < 0 ? 'done' : distance === 0 ? 'current' : 'upcoming'
}
