import { type OnboardingFlowContext } from 'scenes/onboarding/legacy/types'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, type TeamType } from '~/types'

import { productAnalyticsOnboarding } from './steps'

function context(overrides: Partial<OnboardingFlowContext> = {}): OnboardingFlowContext {
    return {
        primary: ProductKey.PRODUCT_ANALYTICS,
        secondaries: [],
        role: 'primary',
        currentTeam: null,
        billing: null,
        isCloudOrDev: true,
        subscribedDuringOnboarding: false,
        canInviteTeammates: true,
        ...overrides,
    }
}

describe('productAnalyticsOnboarding.steps', () => {
    // Regression: the session replay step used to render unconditionally, re-pitching
    // replay to users who had just deselected it in the product picker.
    it('does not render the session replay step when the user deselected it', () => {
        const steps = productAnalyticsOnboarding.steps(context({ secondaries: [] }))

        expect(steps.some((step) => step.stepKey === OnboardingStepKey.SESSION_REPLAY)).toBe(false)
    })

    it('renders the session replay step when the user selected session replay', () => {
        const steps = productAnalyticsOnboarding.steps(context({ secondaries: [ProductKey.SESSION_REPLAY] }))

        expect(steps.some((step) => step.stepKey === OnboardingStepKey.SESSION_REPLAY)).toBe(true)
    })

    it('does not render the session replay step when it is already enabled on the team', () => {
        const steps = productAnalyticsOnboarding.steps(
            context({
                secondaries: [ProductKey.SESSION_REPLAY],
                currentTeam: { session_recording_opt_in: true } as TeamType,
            })
        )

        expect(steps.some((step) => step.stepKey === OnboardingStepKey.SESSION_REPLAY)).toBe(false)
    })
})
