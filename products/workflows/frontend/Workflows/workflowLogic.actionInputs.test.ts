import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-action-inputs-1'
const FUNCTION_ACTION_ID = 'action_function_1'

const makeWorkflow = (): HogFlow => ({
    id: WORKFLOW_ID,
    name: 'Action inputs test',
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
            id: FUNCTION_ACTION_ID,
            type: 'function',
            name: 'Slack',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: {
                template_id: 'template-slack',
                inputs: { icon_emoji: { value: ':hedgehog:' } },
            },
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
    edges: [
        { from: 'trigger_node', to: FUNCTION_ACTION_ID, type: 'continue' },
        { from: FUNCTION_ACTION_ID, to: 'exit_node', type: 'continue' },
    ],
    conversion: { window_minutes: null, filters: [] },
    exit_condition: 'exit_only_at_end',
    version: 1,
    status: 'draft',
    team_id: 1,
    trigger: { type: 'event', filters: {} } as HogFlow['trigger'],
    created_at: '2026-05-01T00:00:00.000Z',
    updated_at: '2026-05-01T00:00:00.000Z',
})

describe('workflowLogic action inputs', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    const getFunctionInputs = (): Record<string, any> => {
        const action = logic.values.workflow.actions.find((a) => a.id === FUNCTION_ACTION_ID)
        return action && 'inputs' in action.config ? (action.config.inputs ?? {}) : {}
    }

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': makeWorkflow(),
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
    })

    it('composes same-tick partial input writes instead of clobbering them', () => {
        // Picking an integration dispatches two writes back to back: clear the dependent
        // integration_field, then set the integration itself. Both must land (and existing keys
        // must survive) even though the caller's rendered props have not caught up with the
        // first write yet.
        logic.actions.partialSetWorkflowActionInputs(FUNCTION_ACTION_ID, { channel: { value: null } })
        logic.actions.partialSetWorkflowActionInputs(FUNCTION_ACTION_ID, { slack_workspace: { value: 7 } })

        expect(getFunctionInputs()).toEqual({
            icon_emoji: { value: ':hedgehog:' },
            channel: { value: null },
            slack_workspace: { value: 7 },
        })
    })
})
