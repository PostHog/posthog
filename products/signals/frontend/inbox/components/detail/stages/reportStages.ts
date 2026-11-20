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

/** Each stage answers one question, shown under the stage tabs. */
export const REPORT_STAGE_QUESTION: Record<ReportStage, string> = {
    spec: 'What did we find?',
    execute: 'What should change?',
    measure: 'Did the fix work?',
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
    | 'actionability'
    | 'already_addressed'
    | 'monitoring_started_at'
>

function workStarted(report: StagedReport): boolean {
    return reportPullRequests(report).length > 0 || !!report.implementation_in_flight || !!report.assignee
}

/**
 * The stages that apply to the report. A report that needs no change, with no work on it, has nothing to
 * execute or measure. A report the judges have not looked at yet keeps every stage.
 */
export function availableReportStages(report: StagedReport): ReportStage[] {
    const needsChange = report.actionability !== 'not_actionable' && report.already_addressed !== true
    if (needsChange || workStarted(report)) {
        return [...REPORT_STAGES]
    }
    return report.monitoring_started_at ? ['spec', 'measure'] : ['spec']
}

/** The stage the report's work has reached. A report opens on this stage. */
export function currentReportStage(report: StagedReport): ReportStage {
    const available = availableReportStages(report)
    const reached: ReportStage = MEASURE_STATUSES.includes(report.status)
        ? 'measure'
        : workStarted(report)
          ? 'execute'
          : 'spec'
    return available.includes(reached) ? reached : 'spec'
}

export function reportStageProgress(stage: ReportStage, report: StagedReport): ReportStageProgress {
    if (report.status === SignalReportStatus.RESOLVED) {
        return 'done'
    }
    const distance = REPORT_STAGES.indexOf(stage) - REPORT_STAGES.indexOf(currentReportStage(report))
    return distance < 0 ? 'done' : distance === 0 ? 'current' : 'upcoming'
}
