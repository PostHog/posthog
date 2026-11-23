import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from './workflowLogic'

describe('workflowLogic load errors', () => {
    let captureException: jest.SpyInstance

    beforeEach(() => {
        captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        captureException.mockRestore()
    })

    it.each([
        { status: 404, reported: false },
        { status: 500, reported: true },
    ])('a $status loading the workflow is reported: $reported', async ({ status, reported }) => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [status, { detail: 'Not found.' }],
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        const logic = workflowLogic({ id: 'deleted-workflow' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowFailure']).toMatchValues({ originalWorkflow: null })

        expect(captureException).toHaveBeenCalledTimes(reported ? 1 : 0)
    })

    it('loads a step template that the template list leaves out', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': {
                    id: 'push-workflow',
                    name: 'Push',
                    actions: [
                        {
                            id: 'push',
                            type: 'function_push',
                            config: { template_id: 'template-native-push', inputs: {} },
                        },
                    ],
                },
                '/api/projects/:team_id/hog_function_templates/': {
                    results: [{ id: 'template-webhook', name: 'Webhook' }],
                    count: 2,
                },
                '/api/projects/:team_id/hog_function_templates/template-native-push/': {
                    id: 'template-native-push',
                    name: 'Push notification',
                },
            },
        })
        initKeaTests()
        const logic = workflowLogic({ id: 'push-workflow' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadMissingHogFunctionTemplatesSuccess'])

        expect(Object.keys(logic.values.hogFunctionTemplatesById).sort()).toEqual([
            'template-native-push',
            'template-webhook',
        ])
    })
})
