import { expectLogic } from 'kea-test-utils'

import { silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-load-errors-1'

describe('workflowLogic load errors', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let getResponse: () => [number, any]

    beforeEach(() => {
        silenceKeaLoadersErrors()
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => getResponse(),
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
    })

    // A genuine 404 (workflow gone) and any other failure (403, 500, dropped request) must be
    // distinguishable so the scene shows "deleted" only for 404 and offers a retry otherwise.
    it.each([[404], [403], [500]])('records status %s on a failed load', async (status) => {
        getResponse = () => [status, { detail: 'boom' }]
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowFailure'])
        expect(logic.values.originalWorkflow).toBeNull()
        expect(logic.values.workflowLoadError).toEqual({ status })
    })

    it('clears the error when a retry succeeds', async () => {
        getResponse = () => [500, { detail: 'boom' }]
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowFailure'])
        expect(logic.values.workflowLoadError).toEqual({ status: 500 })

        getResponse = () => [200, { id: WORKFLOW_ID, name: 'Recovered' }]
        await expectLogic(logic, () => {
            logic.actions.loadWorkflow()
        }).toDispatchActions(['loadWorkflow', 'loadWorkflowSuccess'])
        expect(logic.values.workflowLoadError).toBeNull()
    })
})
