import { SetupTaskId } from 'lib/components/ProductSetup'
import { LogsSDKInstructions } from 'scenes/onboarding/legacy/sdks/logs/LogsSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const logsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.LOGS}`,
            productKey: ProductKey.LOGS,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            setupTaskId: SetupTaskId.EnableLogCapture,
            // Logs uses OpenTelemetry, not posthog-js — no dedup with the analytics products.
            // Future OTel-based products would set the same dedupKey to share this step.
            dedupKey: INSTALL_DEDUP_KEYS.OPENTELEMETRY,
            render: () => <OnboardingInstallStep sdkInstructionMap={LogsSDKInstructions} hideInstallationCheck />,
        },
    ],
    completeRedirectUrl: () => urls.logs(),
}
