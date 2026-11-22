import { useActions, useValues } from 'kea'

import { setupDetectionLogic } from 'lib/components/ProductEmptyState/setupDetectionLogic'
import { SetupListeningIndicator } from 'lib/components/ProductEmptyState/SetupListeningIndicator'
import { onboardingLogic } from 'scenes/onboarding/onboardingLogic'
import { reportOnboardingStepCompleted } from 'scenes/onboarding/onboardingUsage'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { metricsSetupDetection } from '../emptyState/metricsSetupDetection'

export function MetricsOnboardingListeningIndicator(): JSX.Element {
    const { hasNextStep, currentStepProductKey } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep } = useActions(onboardingLogic)

    // Advance through onboarding like the install step's Next button, so completion is recorded
    // and any remaining steps of a multi-product flow still run.
    const advance = (): void => {
        reportOnboardingStepCompleted(OnboardingStepKey.INSTALL, currentStepProductKey ?? undefined)
        if (hasNextStep) {
            goToNextStep()
        } else {
            completeOnboarding()
        }
    }

    return (
        <SetupListeningIndicator
            productKey={ProductKey.METRICS}
            statusLogic={setupDetectionLogic(metricsSetupDetection)}
            dataName="metric"
            destination={{ label: 'Continue', onClick: advance }}
        />
    )
}
