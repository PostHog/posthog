import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-duplicate-1'

const WORKFLOW: HogFlow = {
    id: WORKFLOW_ID,
    name: 'Duplicate test',
    actions: [
        {
            id: 'trigger_node',
            type: 'trigger',
            name: 'Trigger',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { type: 'event', filters: {} },
        },
        {
            id: 'exit_node',
            type: 'exit',
            name: 'Exit',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { reason: 'Default exit' },
        },
    ],
    edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
}

describe('workflowLogic duplicate', () => {
    let logic: ReturnType<typeof workflowLogic.build>
    let createCalls: number
    let releaseCreate: () => void

    beforeEach(async () => {
        createCalls = 0
        let release = (): void => {}
        const createHeld = new Promise<void>((resolve) => {
            release = resolve
        })
        releaseCreate = release

        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': WORKFLOW,
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
            post: {
                '/api/environments/:team_id/hog_flows/': async () => {
                    createCalls += 1
                    await createHeld
                    return [200, { ...WORKFLOW, id: 'wf-duplicate-copy' }]
                },
            },
        })

        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
    })

    it('creates only one copy when duplicate fires twice before the request settles', async () => {
        logic.actions.duplicate()
        logic.actions.duplicate()

        releaseCreate()
        await expectLogic(logic).toFinishAllListeners()

        expect(createCalls).toBe(1)
    })

    it('accepts a later duplicate once the request has settled', async () => {
        logic.actions.duplicate()
        releaseCreate()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.duplicate()
        await expectLogic(logic).toFinishAllListeners()

        expect(createCalls).toBe(2)
    })
})
