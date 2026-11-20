import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport } from '../../../types'
import { ReportMetricSeriesPoints } from '../../../utils/reportMetrics'
import { ReportCheckItem } from './ReportCheckItem'
import { ReportMonitoringWindow } from './ReportMonitoringWindow'
import { ReportOutcomeCard } from './ReportOutcomeCard'
import { ReportStageSectionTitle } from './ReportStageSectionTitle'

/** Whether the fix held: the metric across the release, the observation window, and the follow-up checks. */
export function ReportMeasureStage({
    report,
    checks,
    metricPoints,
}: {
    report: SignalReport
    checks: SignalReportCheckApi[]
    /** The primary metric by day, through now. Null while it loads or when the report has no metric. */
    metricPoints: ReportMetricSeriesPoints | null
}): JSX.Element {
    const primaryMetric = report.metrics?.find((metric) => metric.role === 'primary') ?? null
    const startedAt = report.monitoring_started_at ?? null
    const openChecks = checks.filter((check) => check.status !== 'cancelled')
    const endsAt =
        openChecks
            .map((check) => check.monitoring_timing?.ends_at)
            .filter((value): value is string => !!value)
            .sort()
            .pop() ?? null

    return (
        <div className="flex flex-col gap-8">
            {startedAt ? (
                <section className="flex flex-col gap-4" aria-label="Outcome">
                    <ReportStageSectionTitle>Outcome</ReportStageSectionTitle>
                    {endsAt && <ReportMonitoringWindow startedAt={startedAt} endsAt={endsAt} />}
                    {primaryMetric && metricPoints && (
                        <ReportOutcomeCard
                            metric={primaryMetric}
                            points={metricPoints}
                            monitoringStartedAt={startedAt}
                        />
                    )}
                </section>
            ) : (
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>Nothing to measure yet</EmptyTitle>
                        <EmptyDescription>
                            Monitoring starts when the fix merges. The follow-up checks then verify the outcome.
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            )}
            {openChecks.length > 0 && (
                <section className="flex flex-col gap-3" aria-label="Follow-up checks">
                    <ReportStageSectionTitle>Follow-up checks</ReportStageSectionTitle>
                    <div className="flex flex-col gap-2">
                        {openChecks.map((check) => (
                            <ReportCheckItem key={check.id} check={check} />
                        ))}
                    </div>
                </section>
            )}
        </div>
    )
}
