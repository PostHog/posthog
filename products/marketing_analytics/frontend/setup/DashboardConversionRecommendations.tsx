import { useActions, useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { conversionGoalFormLogic } from './conversionGoalFormLogic'
import { ConversionGoalRecommendations } from './ConversionGoalRecommendations'
import { DashboardSetupPrompt } from './DashboardSetupPrompt'
import { dashboardSetupPromptsLogic } from './dashboardSetupPromptsLogic'

export function DashboardConversionRecommendations(): JSX.Element | null {
    const { setupEnabled } = useValues(marketingAnalyticsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { user } = useValues(userLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { openSetup } = useActions(dashboardSetupPromptsLogic({ projectId: currentTeamId ?? -1, userId: user?.uuid }))
    const { selectRecommendation, requestFormFocus } = useActions(
        conversionGoalFormLogic({ projectId: currentTeamId ?? -1 })
    )

    if (!setupEnabled || !featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI]) {
        return null
    }

    return (
        <DashboardSetupPrompt kind="conversion-goals">
            {(dismissButton) => (
                <ConversionGoalRecommendations
                    headerAction={dismissButton}
                    hideWhenConfigured
                    onConfigureGoals={() => {
                        requestFormFocus()
                        openSetup('conversion-goals')
                    }}
                    onUseSuggestion={(recommendation) => {
                        selectRecommendation(recommendation)
                        openSetup('conversion-goals')
                    }}
                />
            )}
        </DashboardSetupPrompt>
    )
}
