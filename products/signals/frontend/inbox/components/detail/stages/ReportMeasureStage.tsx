import { ReactNode } from 'react'

import { Button, Empty, EmptyDescription, EmptyHeader, EmptyTitle, Skeleton, Text } from '@posthog/quill'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport } from '../../../types'
import { ReportMetricSeriesPoints } from '../../../utils/reportMetrics'
import { OBSERVATION_CHART_HEIGHT_CLASS } from '../ReportObservationChart'
import { ReportCheckItem } from './ReportCheckItem'
import { ReportMonitoringWindow } from './ReportMonitoringWindow'
import { ReportOutcomeCard } from './ReportOutcomeCard'
import { ReportStageDetails } from './ReportStageDetails'
import { ReportStageSectionTitle } from './ReportStageSectionTitle'

/** Whether the fix held: the metric across the release, the observation window, and the follow-up checks. */
export function ReportMeasureStage({
    report,
    checks,
    metricPoints,
    metricLoading = false,
    metricFailed = false,
    onMetricRetry,
    children,
}: {
    report: SignalReport
    checks: SignalReportCheckApi[]
    /** The detail lines of this stage. */
    children?: ReactNode
    /** The primary metric's chart buckets, through now. Null while it loads, when it fails, or when the report has no metric. */
    metricPoints: ReportMetricSeriesPoints | null
    metricLoading?: boolean
    metricFailed?: boolean
    onMetricRetry?: () => void
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
                    {primaryMetric && metricPoints ? (
                        <ReportOutcomeCard
                            metric={primaryMetric}
                            points={metricPoints}
                            monitoringStartedAt={startedAt}
                        />
                    ) : primaryMetric && metricLoading ? (
                        <Skeleton className={`${OBSERVATION_CHART_HEIGHT_CLASS} w-full`} aria-busy />
                    ) : primaryMetric && metricFailed ? (
                        <div className="flex flex-wrap items-center gap-2" data-attr="inbox-report-outcome-error">
                            <Text size="sm" variant="muted" render={<p className="m-0" />}>
                                Couldn't load the metric chart.
                            </Text>
                            {onMetricRetry && (
                                <Button size="sm" variant="outline" onClick={onMetricRetry}>
                                    Try again
                                </Button>
                            )}
                        </div>
                    ) : null}
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
            <ReportStageDetails>{children}</ReportStageDetails>
        </div>
    )
}
