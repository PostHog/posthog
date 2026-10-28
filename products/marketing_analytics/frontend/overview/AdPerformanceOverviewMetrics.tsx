import { useValues } from 'kea'

import type { ChartTheme } from '@posthog/quill-charts'

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
    sparklineTheme?: ChartTheme
    labelFromKey: (key: string) => React.ReactNode
    viewKey: string
}

export function AdPerformanceOverviewMetrics({
    items,
    loading,
    samplingRate,
    sparklineTheme,
    labelFromKey,
    viewKey,
}: AdPerformanceOverviewMetricsProps): JSX.Element {
    const logic = overviewMetricsLogic({ viewKey })
    const { selection } = useValues(logic)
    const shown = shownOverviewMetrics(items, selection)

    return (
        <div className="flex flex-col gap-2">
            <OverviewMetricCardGrid
                sparklineTheme={sparklineTheme}
                className="grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]"
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
