import { SetupTaskId } from 'lib/components/ProductSetup'
import {
    LLMAnalyticsSDKInstructions,
    LLMAnalyticsSDKTagOverrides,
} from 'scenes/onboarding/sdks/llm-analytics/LLMAnalyticsSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/sdks/OnboardingInstallStep'
import { type StepProvider } from 'scenes/onboarding/types'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const llmAnalyticsOnboardingSteps: StepProvider = (ctx) => [
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
]
