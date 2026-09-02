import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowsLogic } from './workflowsLogic'

const CREATED_WORKFLOW = { id: 'wf-created', name: 'Just created', status: 'draft' } as HogFlow
const EXISTING_WORKFLOW = { id: 'wf-existing', name: 'Already there', status: 'active' } as HogFlow

describe('workflowsLogic', () => {
    let logic: ReturnType<typeof workflowsLogic.build>
    let listResults: HogFlow[]
    let listCalls: number

    beforeEach(() => {
        listCalls = 0
        listResults = [EXISTING_WORKFLOW]
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/': () => {
                    listCalls += 1
                    return [200, { results: listResults, count: listResults.length }]
                },
            },
        })
        initKeaTests()
        logic = workflowsLogic()
        logic.mount()
    })

    it('re-reads the list when it came back without the workflow just created', async () => {
        logic.actions.workflowCreated(CREATED_WORKFLOW)
        logic.actions.loadWorkflows()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        expect(logic.values.pendingCreatedWorkflowId).toBe(CREATED_WORKFLOW.id)

        listResults = [CREATED_WORKFLOW, EXISTING_WORKFLOW]
        await expectLogic(logic).toDispatchActions(['loadWorkflows', 'loadWorkflowsSuccess'])

        expect(listCalls).toBe(2)
        expect(logic.values.workflows.results).toEqual([CREATED_WORKFLOW, EXISTING_WORKFLOW])
        expect(logic.values.pendingCreatedWorkflowId).toBeNull()
    })

    // Clearing the id is what bounds the re-read, so a filter that legitimately excludes the
    // workflow costs one extra request rather than looping.
    it.each([
        ['the first response already contains it', [CREATED_WORKFLOW, EXISTING_WORKFLOW], 1],
        ['no response ever contains it', [EXISTING_WORKFLOW], 2],
    ] as [string, HogFlow[], number][])('stops re-reading when %s', async (_name, results, expectedCalls) => {
        listResults = results
        logic.actions.workflowCreated(CREATED_WORKFLOW)
        logic.actions.loadWorkflows()

        await expectLogic(logic).toDispatchActions(
            expectedCalls === 1
                ? ['loadWorkflowsSuccess']
                : ['loadWorkflowsSuccess', 'loadWorkflows', 'loadWorkflowsSuccess']
        )
        await expectLogic(logic).toFinishAllListeners()

        expect(listCalls).toBe(expectedCalls)
        expect(logic.values.pendingCreatedWorkflowId).toBeNull()
    })
})
