import { SetupTaskId } from 'lib/components/ProductSetup'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { type ProductOnboardingProvider } from 'products/growth/frontend/onboarding/flow/types'
import {
    LLMAnalyticsSDKInstructions,
    LLMAnalyticsSDKTagOverrides,
} from 'products/growth/frontend/onboarding/sdks/llm-analytics/LLMAnalyticsSDKInstructions'
import { OnboardingInstallStep } from 'products/growth/frontend/onboarding/sdks/OnboardingInstallStep'

export const llmAnalyticsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.LLM_ANALYTICS}`,
            productKey: ProductKey.LLM_ANALYTICS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            setupTaskId: SetupTaskId.IngestFirstLlmEvent,
            render: () => (
                <OnboardingInstallStep
                    sdkInstructionMap={LLMAnalyticsSDKInstructions}
                    sdkTagOverrides={LLMAnalyticsSDKTagOverrides}
                    listeningForName="LLM generation"
                />
            ),
        },
    ],
    completeRedirectUrl: () => urls.llmAnalyticsDashboard(),
}
