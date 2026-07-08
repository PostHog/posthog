import { SetupTaskId } from 'lib/components/ProductSetup'
import { OnboardingErrorTrackingAlertsStep } from 'scenes/onboarding/legacy/error-tracking/OnboardingErrorTrackingAlertsStep'
import { OnboardingErrorTrackingSourceMapsStep } from 'scenes/onboarding/legacy/error-tracking/OnboardingErrorTrackingSourceMapsStep'
import { ErrorTrackingSDKInstructions } from 'scenes/onboarding/legacy/sdks/error-tracking/ErrorTrackingSDKInstructions'
import { OnboardingInstallStep } from 'scenes/onboarding/legacy/sdks/OnboardingInstallStep'
import { INSTALL_DEDUP_KEYS, type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

export const errorTrackingOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => {
        const installStep = {
            id: `${OnboardingStepKey.INSTALL}:${ProductKey.ERROR_TRACKING}`,
            productKey: ProductKey.ERROR_TRACKING,
            stepKey: OnboardingStepKey.INSTALL,
            role: ctx.role,
            setupTaskId: SetupTaskId.EnableErrorTracking,
            // Same posthog-js install as Product Analytics / Web Analytics / etc. When
            // those products are also picked, only one install step is shown — but the
            // `EnableErrorTracking` task still gets ticked because the dedup pass merges
            // setupTaskIds from dropped descriptors into the survivor.
            dedupKey: INSTALL_DEDUP_KEYS.POSTHOG_JS,
            render: () => <OnboardingInstallStep sdkInstructionMap={ErrorTrackingSDKInstructions} />,
        }
        if (ctx.role === 'secondary') {
            return [installStep]
        }
        return [
            installStep,
            {
                id: `${OnboardingStepKey.SOURCE_MAPS}:${ProductKey.ERROR_TRACKING}`,
                productKey: ProductKey.ERROR_TRACKING,
                stepKey: OnboardingStepKey.SOURCE_MAPS,
                role: ctx.role,
                setupTaskId: SetupTaskId.UploadSourceMaps,
                render: () => <OnboardingErrorTrackingSourceMapsStep />,
            },
            {
                id: `${OnboardingStepKey.ALERTS}:${ProductKey.ERROR_TRACKING}`,
                productKey: ProductKey.ERROR_TRACKING,
                stepKey: OnboardingStepKey.ALERTS,
                role: ctx.role,
                render: () => <OnboardingErrorTrackingAlertsStep />,
            },
        ]
    },
    completeRedirectUrl: () => urls.errorTracking(),
}
