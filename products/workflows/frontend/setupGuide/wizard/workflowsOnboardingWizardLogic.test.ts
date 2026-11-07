import { waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowsSetupGuideLogic } from '../workflowsSetupGuideLogic'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

describe('workflowsOnboardingWizardLogic', () => {
    let logic: ReturnType<typeof workflowsOnboardingWizardLogic.build>

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 9, kind: 'email', config: { provider: 'sandbox', verified: true } }],
                },
                '/api/projects/:project_id/messaging_categories/': { results: [], count: 0 },
                '/api/environments/:team_id/messaging_templates/': { results: [] },
                '/api/projects/:project_id/hog_flows/': { results: [], count: 0 },
            },
        })
        logic = workflowsOnboardingWizardLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('leaves the email channel and domain steps open when only the sandbox sender exists', async () => {
        await waitFor(() => expect(workflowsSetupGuideLogic.values.steps).not.toBeNull())

        expect(workflowsSetupGuideLogic.values.steps?.filter((step) => step.done).map((step) => step.key)).toEqual([])
        expect(logic.values.stepDone).toMatchObject({ channel: false, domain: false })
    })
})
