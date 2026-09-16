import { MarketingMetricCardGrid } from '../cards/MarketingMetricCardGrid'
import { RetentionCards } from '../cards/RetentionCards'
import { RetentionBreakdownTable } from '../tables/RetentionBreakdownTable'

export function RetentionSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <MarketingMetricCardGrid>
                <RetentionCards />
            </MarketingMetricCardGrid>
            <RetentionBreakdownTable />
        </div>
    )
}
