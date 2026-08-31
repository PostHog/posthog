import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { signalsFeaturesCreate } from 'products/signals/frontend/generated/api'

import { featureCreateLogic } from './featureCreateLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsFeaturesCreate: jest.fn(),
}))

const mockCreateFeature = jest.mocked(signalsFeaturesCreate)

describe('featureCreateLogic', () => {
    let logic: ReturnType<typeof featureCreateLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockCreateFeature.mockReset()
        mockCreateFeature.mockResolvedValue({
            report_id: 'feature-report-id',
            task_id: 'planning-task-id',
            run_id: 'planning-run-id',
        })
        logic = featureCreateLogic.build()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens the planning tab after creating the feature and its first planning task', async () => {
        logic.actions.setDescriptionDraft('Build a durable widget')

        await expectLogic(logic, () => logic.actions.createFeature()).toFinishAllListeners()

        expect(mockCreateFeature).toHaveBeenCalledWith(String(MOCK_TEAM_ID), {
            initial_description: 'Build a durable widget',
        })
        expect(router.values.location.pathname).toContain('/inbox/features/feature-report-id')
        expect(router.values.searchParams.feature_tab).toBe('planning')
    })
})
