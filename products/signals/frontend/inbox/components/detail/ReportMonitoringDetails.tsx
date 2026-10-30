import type { ReactNode } from 'react'

import type {
    MetricThresholdConfigApi,
    MonitoringMetricConfigApi,
    ReportMetricApi,
} from 'products/signals/frontend/generated/api.schemas'

import { formatReportMetricValue } from '../../utils/reportMetrics'
import { monitoringPeriodLabel } from './reportCheckPresentation'

export function ReportMonitoringDetails({
    config,
    monitoring,
    metric,
    timingDescription,
}: {
    config: MetricThresholdConfigApi
    monitoring: MonitoringMetricConfigApi
    metric: ReportMetricApi
    timingDescription: ReactNode
}): JSX.Element {
    return (
        <details className="text-sm">
            <summary className="cursor-pointer">View measurement details</summary>
            <div className="mt-2 flex flex-col gap-1 text-secondary">
                <p className="m-0">Measurement window: since Monitoring starts.</p>
                <p className="m-0">{`Target reference period: ${monitoringPeriodLabel(monitoring.reference_period_minutes)}.`}</p>
                <p className="m-0">
                    {monitoring.threshold_scaling === 'linear'
                        ? 'The target scales in proportion to elapsed time.'
                        : 'The target stays fixed as the measurement period grows.'}
                </p>
                <p className="m-0">The chart shows surrounding activity. Future dates have no measurements.</p>
                <p className="m-0">
                    Target lines show a reference for a full chart interval. Individual buckets do not decide the
                    outcome.
                </p>
                {config.baseline_value != null && (
                    <p className="m-0">
                        <span>{`Baseline: ${formatReportMetricValue(metric, config.baseline_value) ?? config.baseline_value}`}</span>
                        {monitoring.baseline_period_minutes != null && (
                            <span>{` · Measured over ${monitoringPeriodLabel(monitoring.baseline_period_minutes)}`}</span>
                        )}
                    </p>
                )}
                <div>{timingDescription}</div>
            </div>
        </details>
    )
}
