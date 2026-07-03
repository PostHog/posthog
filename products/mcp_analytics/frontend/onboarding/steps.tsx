import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { onboardingLogic } from 'scenes/onboarding/legacy/onboardingLogic'
import { OnboardingStep } from 'scenes/onboarding/legacy/OnboardingStep'
import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { MCPAnalyticsInstallHero } from './MCPAnalyticsInstall'

function MCPAnalyticsInstallStep(): JSX.Element {
    const { onboardingState } = useValues(mcpAnalyticsOnboardingLogic)
    const { completeOnboarding } = useActions(onboardingLogic)

    // The moment tool calls start flowing the setup worked — whisk them to their data
    // instead of making them click "Go to dashboard".
    useEffect(() => {
        if (onboardingState === 'onboarded') {
            completeOnboarding()
        }
    }, [onboardingState, completeOnboarding])

    return (
        <OnboardingStep title="Install" stepKey={OnboardingStepKey.INSTALL} continueText="Go to dashboard">
            <div className="mt-6">
                <MCPAnalyticsInstallHero />
            </div>
        </OnboardingStep>
    )
}

export const mcpAnalyticsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.MCP_ANALYTICS}`,
            productKey: ProductKey.MCP_ANALYTICS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            render: () => <MCPAnalyticsInstallStep />,
        },
    ],
    completeRedirectUrl: () => urls.mcpAnalyticsDashboard(),
}
