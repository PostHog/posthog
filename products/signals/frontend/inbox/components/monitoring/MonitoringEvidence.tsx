import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import type { ReportMonitoringSummaryApi, SignalReportListApi } from 'products/signals/frontend/generated/api.schemas'

import { monitoringEvidence, monitoringReadingOverdue } from '../../utils/monitoringTimeline'
import { monitoringDisplayState, monitoringFigures } from '../../utils/reportMonitoringSummary'
import { MonitoringEvidenceChart } from './MonitoringEvidenceChart'
import { MonitoringWaitingNote } from './MonitoringWaitingNote'

function FiguresLine({
    report,
    summary,
}: {
    report: SignalReportListApi
    summary: ReportMonitoringSummaryApi
}): JSX.Element | null {
    const metricId = summary.lead_check?.metric_id
    const interval = metricId ? report.metrics.find((m) => m.metric_id === metricId)?.interval : null
    const figures = monitoringFigures(summary, interval)
    if (!figures || (!figures.before && !figures.sinceFix)) {
        return null
    }
    return (
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-secondary">
            <span>
                Before the fix <span className="font-semibold text-primary">{figures.before ?? '–'}</span>
            </span>
            <span>
                Since the fix <span className="font-semibold text-primary">{figures.sinceFix ?? '–'}</span>
            </span>
            <span className="text-tertiary">{figures.basis}</span>
        </div>
    )
}

/** The lead check's evidence for a fix still being checked: its chart when one can be drawn, otherwise the window. */
export function MonitoringEvidence({
    report,
    summary,
    now,
}: {
    report: SignalReportListApi
    summary: ReportMonitoringSummaryApi
    now: number
}): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const lead = summary.lead_check
    const evidence =
        monitoringDisplayState(summary, now) === 'readings_hidden' ? null : monitoringEvidence(report, timezone)
    const nextReading = lead?.next_measurement_at
    return (
        <div className="flex flex-col gap-2">
            {lead ? <div className="text-xs font-semibold text-secondary">{lead.title}</div> : null}
            {evidence ? (
                <MonitoringEvidenceChart summary={summary} evidence={evidence} now={now} />
            ) : (
                <MonitoringWaitingNote summary={summary} now={now} />
            )}
            <FiguresLine report={report} summary={summary} />
            {nextReading && monitoringReadingOverdue(report, now) ? (
                <div className="flex items-center gap-1.5 text-xs text-warning">
                    <IconWarning className="size-3.5 shrink-0" />
                    A reading was due {dayjs(nextReading).from(dayjs(now))} and hasn't run yet. The verdict still runs
                    on time.
                </div>
            ) : null}
        </div>
    )
}
