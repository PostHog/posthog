import { useValues } from 'kea'

import {
    MarketingDashboardView,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { MarketingDashboardHeader } from './header/MarketingDashboardHeader'
import { AcquisitionSection } from './sections/AcquisitionSection'
import { ConversionSection } from './sections/ConversionSection'
import { EngagementSection } from './sections/EngagementSection'
import { OverviewSection } from './sections/OverviewSection'
import { RetentionSection } from './sections/RetentionSection'

const SECTIONS: Record<MarketingDashboardView, () => JSX.Element> = {
    [MarketingDashboardView.OVERVIEW]: OverviewSection,
    [MarketingDashboardView.ACQUISITION]: AcquisitionSection,
    [MarketingDashboardView.ENGAGEMENT]: EngagementSection,
    [MarketingDashboardView.RETENTION]: RetentionSection,
    [MarketingDashboardView.CONVERSION]: ConversionSection,
}

export function NewMarketingAnalyticsDashboard(): JSX.Element {
    const { dashboardView } = useValues(marketingAnalyticsLogic)
    const Section = SECTIONS[dashboardView]

    return (
        <div className="mt-4 flex flex-col gap-4">
            <MarketingDashboardHeader />
            <div id="marketing-dashboard-section" className="flex flex-col gap-4">
                <Section />
            </div>
        </div>
    )
}
