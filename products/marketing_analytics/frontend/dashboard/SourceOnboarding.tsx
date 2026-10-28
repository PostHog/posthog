import { useActions, useValues } from 'kea'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { marketingOnboardingLogic } from 'scenes/marketing-analytics/Onboarding/marketingOnboardingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { MarketingAnalyticsSourceStatusBanner } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { detectedSourcesLogic } from 'products/marketing_analytics/frontend/dashboard/detectedSourcesLogic'
import { SearchConsoleSource } from 'products/marketing_analytics/frontend/dashboard/SearchConsoleSource'
import { SourceOnboardingScan } from 'products/marketing_analytics/frontend/dashboard/SourceOnboardingScan'

import { SourceCatalog } from './SourceCatalog'

export function SourceOnboarding({ completeOnboarding }: { completeOnboarding: () => void }): JSX.Element {
    const { reportMarketingAnalyticsOnboardingViewed, reportMarketingAnalyticsOnboardingCompleted } =
        useActions(eventUsageLogic)
    const { addProductIntent } = useActions(teamLogic)
    const { currentTeamId } = useValues(teamLogic)
    useValues(detectedSourcesLogic({ teamId: currentTeamId ?? 0 }))
    const { setupPlan, setupPlanLoading, visibleSuggestions, dismissedSuggestions, sourceScanDisabledReason } =
        useValues(setupPlanLogic)
    const { rescanSources, restoreAllDismissed } = useActions(setupPlanLogic)
    const { showManualSources } = useValues(marketingOnboardingLogic)
    const { setShowManualSources } = useActions(marketingOnboardingLogic)
    const { hasSources } = useValues(marketingAnalyticsLogic)

    useOnMountEffect(() => {
        reportMarketingAnalyticsOnboardingViewed()
    })

    const handleComplete = (): void => {
        reportMarketingAnalyticsOnboardingCompleted(hasSources)
        addProductIntent({
            product_type: ProductKey.MARKETING_ANALYTICS,
            intent_context: ProductIntentContext.MARKETING_ANALYTICS_ONBOARDING_COMPLETED,
            metadata: { has_sources: hasSources },
        })
        completeOnboarding()
    }

    return (
        <div className="space-y-4">
            <MarketingAnalyticsSourceStatusBanner />
            {showManualSources ? (
                <SourceCatalog
                    onContinue={handleComplete}
                    hasSources={hasSources}
                    onBack={() => setShowManualSources(false)}
                />
            ) : (
                <SourceOnboardingScan
                    loading={setupPlanLoading && !setupPlan}
                    failed={!setupPlan && !setupPlanLoading}
                    suggestions={visibleSuggestions.filter(
                        (suggestion) =>
                            suggestion.kind === 'connect_source' && suggestion.apply?.op === 'open_source_wizard'
                    )}
                    dismissed={dismissedSuggestions.some((suggestion) => suggestion.kind === 'connect_source')}
                    onRestore={restoreAllDismissed}
                    onManual={() => setShowManualSources(true)}
                    onContinue={handleComplete}
                    onRescan={rescanSources}
                    rescanLoading={setupPlanLoading}
                    rescanDisabledReason={sourceScanDisabledReason}
                />
            )}
            <SearchConsoleSource />
        </div>
    )
}
