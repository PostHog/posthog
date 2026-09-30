import { OverviewMetricCardGrid } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'

import type { MetricCardSpec } from './metricCardSpec'
import { MetricNoticeCard } from './MetricNoticeCard'

export interface MarketingMetricCardProps {
    spec?: MetricCardSpec
    loading: boolean
    labelFromKey: (key: string) => React.ReactNode
}

/** One card per grid instance, so a notice keeps its place in the configured order instead of
 * being pushed past every metric. */
export function MarketingMetricCard({ spec, loading, labelFromKey }: MarketingMetricCardProps): JSX.Element | null {
    if (loading) {
        return (
            <OverviewMetricCardGrid layout="contents" items={[]} loading numSkeletons={1} labelFromKey={labelFromKey} />
        )
    }
    if (!spec) {
        return null
    }
    if (spec.kind === 'notice') {
        return <MetricNoticeCard title={spec.title} message={spec.message} value={spec.value} action={spec.action} />
    }
    return (
        <OverviewMetricCardGrid
            layout="contents"
            items={[spec.item]}
            loading={false}
            numSkeletons={1}
            labelFromKey={labelFromKey}
        />
    )
}
