import { isWizardRepositoryEligible } from './WizardRepositoryPicker'

describe('isWizardRepositoryEligible', () => {
    it.each([
        { archived: false, can_push: false, expected: true },
        { archived: true, can_push: true, expected: false },
    ])('returns $expected for archived=$archived and can_push=$can_push', ({ archived, can_push, expected }) => {
        expect(
            isWizardRepositoryEligible({
                id: 1,
                name: 'posthog',
                full_name: 'PostHog/posthog',
                archived,
                can_push,
            })
        ).toBe(expected)
    })
})
