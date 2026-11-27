import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { projectLogic } from 'scenes/projectLogic'

import type {
    ReportMonitoringSummaryApi,
    SignalReportCheckApi,
    SignalReportListApi,
} from 'products/signals/frontend/generated/api.schemas'

import { monitoringRowLogic } from '../../logics/monitoringRowLogic'
import { monitoringTabLogic } from '../../logics/monitoringTabLogic'
import { monitoringReadingOverdue } from '../../utils/monitoringTimeline'
import { asReportMetricSeriesQuery } from '../../utils/reportMetrics'
import { monitoringFigures, monitoringSummaryTimeline } from '../../utils/reportMonitoringSummary'
import { ReportCheckMetricChart } from '../detail/ReportCheckMetricChart'
import { reportCheckMetric } from '../detail/reportCheckPresentation'
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

interface MonitoringMetricChart {
    check: SignalReportCheckApi
    checkMetric: NonNullable<ReturnType<typeof reportCheckMetric>>
    query: NonNullable<ReturnType<typeof asReportMetricSeriesQuery>>
    timeline: ReturnType<typeof monitoringSummaryTimeline>
}

function monitoringMetricChart(
    summary: ReportMonitoringSummaryApi,
    reportChecks: SignalReportCheckApi[] | null,
    now: number
): MonitoringMetricChart | null {
    const lead = summary.lead_check
    if (!lead || !reportChecks) {
        return null
    }
    const check = reportChecks.find((candidate) => candidate.id === lead.check_id)
    const checkMetric = check ? reportCheckMetric(check) : null
    const query = checkMetric ? asReportMetricSeriesQuery(checkMetric.metric) : null
    if (!check || !checkMetric || !query) {
        return null
    }
    return {
        check,
        checkMetric,
        query,
        timeline: monitoringSummaryTimeline({ ...summary, ends_at: lead.ends_at }, now),
    }
}

function MonitoringMetricEvidence({
    report,
    summary,
    now,
}: {
    report: SignalReportListApi
    summary: ReportMonitoringSummaryApi
    now: number
}): JSX.Element {
    const lead = summary.lead_check
    const { currentProjectId } = useValues(projectLogic)
    const logic = monitoringRowLogic({ reportId: report.id, loadChecks: lead != null })
    const { reportChecks, reportChecksLoadFailed } = useValues(logic)
    const { loadReportChecks } = useActions(logic)

    if (lead && reportChecks === null && !reportChecksLoadFailed) {
        return <LemonSkeleton className="h-36 w-full" />
    }
    if (reportChecksLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadReportChecks() }}>
                Couldn't load the monitoring chart.
            </LemonBanner>
        )
    }
    const chart = monitoringMetricChart(summary, reportChecks, now)
    if (!chart) {
        return <MonitoringWaitingNote summary={summary} now={now} />
    }

    const { check, checkMetric, query, timeline } = chart
    return (
        <ReportCheckMetricChart
            reportId={report.id}
            metric={checkMetric.metric}
            query={query.source}
            goalGrain="whole_window"
            goalBounds={
                checkMetric.config.comparison.operator === 'between' ? checkMetric.config.comparison.bounds : null
            }
            version={`${check.id}.monitoring-tab`}
            timeline={timeline}
            queryTeamId={currentProjectId ?? undefined}
            monitoring={
                checkMetric.config.monitoring
                    ? {
                          referencePeriodMinutes: checkMetric.config.monitoring.reference_period_minutes,
                          thresholdScaling: checkMetric.config.monitoring.threshold_scaling,
                          startedAt: timeline.startedAt,
                          endsAt: timeline.endsAt,
                      }
                    : undefined
            }
        />
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
    const { loadedAt } = useValues(monitoringTabLogic)
    const lead = summary.lead_check
    const nextReading = lead?.next_measurement_at
    return (
        <div className="flex flex-col gap-2">
            {lead ? <div className="text-xs font-semibold text-secondary">{lead.title}</div> : null}
            <MonitoringMetricEvidence report={report} summary={summary} now={now} />
            <FiguresLine report={report} summary={summary} />
            {nextReading && loadedAt != null && monitoringReadingOverdue(report, loadedAt) ? (
                <div className="flex items-center gap-1.5 text-xs text-warning">
                    <IconWarning className="size-3.5 shrink-0" />
                    A reading was due <span translate="no">{dayjs(nextReading).from(dayjs(now))}</span> and hadn't run
                    when this page loaded. The verdict still runs on time.
                </div>
            ) : null}
        </div>
    )
}
