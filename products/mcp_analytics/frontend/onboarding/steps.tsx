import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'
import { useEffect, useRef, useState } from 'react'

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
import { MCPSetupMode } from '../setupMode/MCPSetupMode'
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
    const { searchParams } = useValues(router)
    const { onCompleteOnboardingRedirectUrlOverride } = useValues(onboardingLogic)
    const { completeOnboarding, setOnCompleteOnboardingRedirectUrl } = useActions(onboardingLogic)
    // A destination picked before onboarding started (a `next` link) wins over the scene.
    const [chosenDestination] = useState(onCompleteOnboardingRedirectUrlOverride)
    // Setup mode lives in the URL, so carrying its params keeps the first-call reveal open in the scene.
    const sceneUrl = combineUrl(urls.mcpAnalytics(), {
        [SETUP_PARAM]: searchParams[SETUP_PARAM],
        [SETUP_STEP_PARAM]: searchParams[SETUP_STEP_PARAM],
    }).url
    const latestSceneUrl = useRef(sceneUrl)
    latestSceneUrl.current = sceneUrl

    useEffect(() => {
        if (onboardingState === 'onboarded') {
            completeOnboarding(chosenDestination ? undefined : { redirectUrlOverride: latestSceneUrl.current })
        }
    }, [onboardingState, completeOnboarding, chosenDestination])

    // The redirect runs after the completion request saves. Setup mode can close or move on meanwhile.
    useEffect(() => {
        if (!chosenDestination && onboardingLogic.findMounted()?.values.isCompleting) {
            setOnCompleteOnboardingRedirectUrl(sceneUrl)
        }
    }, [sceneUrl, chosenDestination, setOnCompleteOnboardingRedirectUrl])

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
                <>
                    {/* Loading, or data just landed and the effect above redirects to the scene. Setup mode stays
                        mounted meanwhile, so its first-call screen does not close until the scene takes it over. */}
                    <div className="flex justify-center my-20">
                        <Spinner className="text-2xl" />
                    </div>
                    <MCPSetupMode />
                </>
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
}
