import { isWizardRepositoryEligible } from './WizardRepositoryPicker'

describe('isWizardRepositoryEligible', () => {
    it('includes accessible installation repositories when GitHub reports can_push as false', () => {
        expect(
            isWizardRepositoryEligible({
                id: 1,
                name: 'posthog',
                full_name: 'PostHog/posthog',
                archived: false,
                can_push: false,
            })
        ).toBe(true)
    })

    it('excludes archived repositories', () => {
        expect(
            isWizardRepositoryEligible({
                id: 1,
                name: 'posthog',
                full_name: 'PostHog/posthog',
                archived: true,
                can_push: true,
            })
        ).toBe(false)
    })
})
