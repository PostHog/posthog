import { useValues } from 'kea'

import { appMetricsLogic } from 'lib/components/AppMetrics/appMetricsLogic'
import { AppMetricsTrends } from 'lib/components/AppMetrics/AppMetricsTrends'

import { METRIC_COLORS } from '../Workflows/workflowMetricsSummaryLogic'
import { BroadcastPerformanceLogicProps, sendActivityParams } from './broadcastPerformanceLogic'

const METRIC_LABELS: Record<string, string> = {
    email_sent: 'Sent',
    email_delivered: 'Delivered',
    email_opened: 'Opened',
    email_link_clicked: 'Link clicked',
}

const SERIES_COLORS = Object.fromEntries(
    Object.entries(METRIC_LABELS).map(([metricName, label]) => [metricName, METRIC_COLORS[label]])
)

export function BroadcastSendActivity({ runId, runStartedAt }: BroadcastPerformanceLogicProps): JSX.Element {
    const { appMetricsTrends, appMetricsTrendsLoading } = useValues(
        appMetricsLogic({
            logicKey: `broadcast-send-activity-${runId}`,
            loadOnMount: true,
            loadOnChanges: true,
            forceParams: sendActivityParams(runId, runStartedAt),
        })
    )

    const hasActivity = !!appMetricsTrends?.series.some((series) => series.values.some((value) => value > 0))

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0 text-sm font-semibold">Activity over time</h3>
            {!appMetricsTrendsLoading && appMetricsTrends && !hasActivity ? (
                <span className="text-muted">No email activity recorded for this send yet.</span>
            ) : (
                <AppMetricsTrends
                    appMetricsTrends={appMetricsTrends}
                    loading={appMetricsTrendsLoading}
                    metricLabels={METRIC_LABELS}
                    seriesColors={SERIES_COLORS}
                    className="h-80"
                />
            )}
        </div>
    )
}
