import { useValues } from 'kea'

import { SamplingNotice, SamplingRate } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { OverviewMetricCardGrid, OverviewMetricCardItem } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import { MetricSourceBadge } from '../components/MetricSourceBadge'
import { OverviewMetricConfigModal } from './OverviewMetricConfigModal'
import { MAX_OVERVIEW_METRICS, overviewMetricSource, shownOverviewMetrics } from './overviewMetricConfiguration'
import { overviewMetricsLogic } from './overviewMetricsLogic'

export interface AdPerformanceOverviewMetricsProps {
    items: OverviewMetricCardItem[]
    loading: boolean
    samplingRate?: SamplingRate
    labelFromKey: (key: string) => React.ReactNode
    viewKey: string
}

export function AdPerformanceOverviewMetrics({
    items,
    loading,
    samplingRate,
    labelFromKey,
    viewKey,
}: AdPerformanceOverviewMetricsProps): JSX.Element {
    const logic = overviewMetricsLogic({ viewKey })
    const { selection } = useValues(logic)
    const shown = shownOverviewMetrics(items, selection)

    return (
        <div className="@container/overview-metrics flex flex-col gap-2">
            {!loading && shown.length === 0 && (
                <p className="m-0 text-secondary text-sm" data-attr="marketing-overview-metrics-empty">
                    No metrics for this date range. Try a longer range, or check that your ad sources have synced.
                </p>
            )}
            <OverviewMetricCardGrid
                className="grid-cols-2 @min-[36rem]/overview-metrics:grid-cols-3 @min-[56rem]/overview-metrics:grid-cols-5"
                items={shown}
                loading={loading}
                numSkeletons={MAX_OVERVIEW_METRICS}
                emptyMessage="-"
                labelFromKey={(key) => (
                    <span className="flex items-start justify-between gap-1">
                        {labelFromKey(key)}
                        <MetricSourceBadge source={overviewMetricSource(key)} />
                    </span>
                )}
            />
            <SamplingNotice samplingRate={samplingRate} />
            <OverviewMetricConfigModal items={items} viewKey={viewKey} />
        </div>
    )
}
