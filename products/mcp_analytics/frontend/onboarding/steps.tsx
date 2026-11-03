import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { OnboardingStep } from 'scenes/onboarding/OnboardingStep'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { type ProductOnboardingProvider } from 'scenes/onboarding/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { mcpAnalyticsEmptyState } from '../emptyState/mcpAnalyticsEmptyState'
import { mcpAnalyticsOnboardingLogic } from '../mcpAnalyticsOnboardingLogic'
import { SETUP_PARAM, SETUP_STEP_PARAM } from '../setupMode/setupMode'
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
        <OnboardingStep
            title={`Install ${availableOnboardingProducts[ProductKey.MCP_ANALYTICS].name}`}
            stepKey={OnboardingStepKey.INSTALL}
            continueText="Go to dashboard"
        >
            <div className="mt-6">
                <MCPAnalyticsInstallHero />
            </div>
        </OnboardingStep>
    )
}

/** The scene's own setup screen, so onboarding and the scene never show two different install flows. */
function MCPAnalyticsSetupDoorStep(): JSX.Element {
    const { onboardingState } = useValues(mcpAnalyticsOnboardingLogic)
    const { status } = useValues(productSetupStatusLogic({ productKey: ProductKey.MCP_ANALYTICS }))
    const { completeOnboarding } = useActions(onboardingLogic)

    useEffect(() => {
        if (onboardingState === 'onboarded') {
            // Setup mode lives in the URL, so carrying its params keeps the first-call reveal open in the scene.
            const { [SETUP_PARAM]: setup, [SETUP_STEP_PARAM]: setupStep } = router.values.searchParams
            completeOnboarding({
                redirectUrlOverride: combineUrl(urls.mcpAnalytics(), {
                    [SETUP_PARAM]: setup,
                    [SETUP_STEP_PARAM]: setupStep,
                }).url,
            })
        }
    }, [onboardingState, completeOnboarding])

    return (
        <OnboardingStep
            title={`Install ${availableOnboardingProducts[ProductKey.MCP_ANALYTICS].name}`}
            stepKey={OnboardingStepKey.INSTALL}
            continueText="Go to dashboard"
            hideTitle
            fullWidth
        >
            {status !== 'loading' && status !== 'has-data' ? (
                <ProductEmptyState
                    config={{ ...mcpAnalyticsEmptyState.config, skippable: false }}
                    // A failed detection still gets the install screen, rather than a spinner that never ends.
                    mode={status === 'waiting-for-data' ? 'waiting-for-data' : 'needs-setup'}
                />
            ) : (
                // Loading, or data just landed and the effect above redirects to the scene.
                <div className="flex justify-center my-20">
                    <Spinner className="text-2xl" />
                </div>
            )}
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
            render: () =>
                ctx.featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE] ? (
                    <MCPAnalyticsSetupDoorStep />
                ) : (
                    <MCPAnalyticsInstallStep />
                ),
        },
    ],
    completeRedirectUrl: () => urls.mcpAnalytics(),
}
