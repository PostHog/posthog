import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { RetentionCards } from '../cards/RetentionCards'
import { MetricChart } from '../charts/MetricChart'
import { RetentionBreakdownTable } from '../tables/RetentionBreakdownTable'

export function RetentionSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                <RetentionCards />
            </MarketingMetricCardGrid>
            <MetricChart />
            <RetentionBreakdownTable />
        </div>
    )
}
