import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { marketingOnboardingLogic } from 'scenes/marketing-analytics/Onboarding/marketingOnboardingLogic'
import { Onboarding } from 'scenes/marketing-analytics/Onboarding/Onboarding'
import { teamLogic } from 'scenes/teamLogic'
import { MarketingAnalyticsSourceStatusBanner } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'
import {
    MarketingDashboardView,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { ConversionGoalRecommendationsBanner } from '../setup/ConversionGoalRecommendationsBanner'
import { AskPostHogAi } from './askAi/AskPostHogAi'
import { DashboardSetupSuggestions } from './DashboardSetupSuggestions'
import { DetectedSources } from './DetectedSources'
import { MarketingDashboardHeader } from './header/MarketingDashboardHeader'
import { marketingDashboardLogic } from './marketingDashboardLogic'
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
    const { dashboardView, nativeSources, validExternalTables, loading, dataWarehouseSources } =
        useValues(marketingAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showOnboarding } = useValues(marketingOnboardingLogic)
    const { completeOnboarding } = useActions(marketingOnboardingLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const { reportDashboardSectionViewed } = useActions(marketingAnalyticsLogic)
    const { conversionGoal, revenueQuery } = useValues(marketingDashboardLogic)
    const Section = SECTIONS[dashboardView]

    const reportedSection = useRef<MarketingDashboardView | null>(null)
    useEffect(() => {
        if (currentTeamLoading || reportedSection.current === dashboardView) {
            return
        }
        reportedSection.current = dashboardView
        reportDashboardSectionViewed(dashboardView, { customerGoal: !!conversionGoal, revenueGoal: !!revenueQuery })
    }, [dashboardView, currentTeamLoading, conversionGoal, revenueQuery, reportDashboardSectionViewed])

    const hasSearchConsole =
        !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS] &&
        !!dataWarehouseSources?.results.some((source) => source.source_type === 'GoogleSearchConsole')
    if (
        featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING] &&
        !loading &&
        !hasSearchConsole &&
        nativeSources.length === 0 &&
        validExternalTables.length === 0 &&
        showOnboarding
    ) {
        return <Onboarding completeOnboarding={completeOnboarding} />
    }
    return (
        <div className="flex flex-col gap-4">
            <MarketingDashboardHeader />
            {!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING] && (
                <MarketingAnalyticsSourceStatusBanner />
            )}
            <DetectedSources />
            <DashboardSetupSuggestions />
            <ConversionGoalRecommendationsBanner />
            {/* The trailing space keeps the last table off the bottom edge of the scene. */}
            <div id="marketing-dashboard-section" className="flex flex-col gap-4 pb-8">
                <Section />
                <AskPostHogAi />
            </div>
        </div>
    )
}
