import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { HogFlow } from './hogflows/types'
import { workflowLogic } from './workflowLogic'

const WORKFLOW_ID = 'wf-clock-wait-1'
const WAIT_NODE_ID = 'wait_node'

const conditionOn = (expression: string): Record<string, any> => ({
    filters: { properties: [{ key: expression, type: 'hogql', value: null }] },
})

const makeWorkflow = (expression: string): HogFlow =>
    ({
        id: WORKFLOW_ID,
        name: 'Clock wait validation test',
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
                id: WAIT_NODE_ID,
                type: 'wait_until_condition',
                name: 'Wait',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: { condition: conditionOn(expression), max_wait_duration: '20d' },
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
            { from: 'trigger_node', to: WAIT_NODE_ID, type: 'continue' },
            { from: WAIT_NODE_ID, to: 'exit_node', type: 'continue' },
        ],
        conversion: { window_minutes: null, filters: [] },
        exit_condition: 'exit_only_at_end',
        version: 1,
        status: 'active',
        team_id: 1,
        trigger: { type: 'event', filters: {} },
        created_at: '2026-05-01T00:00:00.000Z',
        updated_at: '2026-05-01T00:00:00.000Z',
    }) as unknown as HogFlow

describe('workflowLogic clock-based wait validation', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    let storedWorkflow: HogFlow

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': () => [200, storedWorkflow],
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    const mountWith = async (expression: string): Promise<void> => {
        storedWorkflow = makeWorkflow(expression)
        initKeaTests()
        logic = workflowLogic({ id: WORKFLOW_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
    }

    it('flags a condition the author builds on the clock', async () => {
        // Nothing wakes such a wait, so the API refuses it. Catching it here is what keeps the
        // author from meeting that refusal only after they save.
        await mountWith("person.properties.plan == 'pro'")

        logic.actions.partialSetWorkflowActionConfig(WAIT_NODE_ID, {
            condition: conditionOn('now() >= toDateTime(person.properties.expires_at)'),
        })

        const result = logic.values.actionValidationErrorsById[WAIT_NODE_ID]
        expect(result?.valid).toBe(false)
        expect(result?.errors.condition).toContain('now()')
        expect(result?.errors.condition).toContain('use a delay step')
    })

    it('leaves a condition a stream can wake alone', async () => {
        await mountWith("toDateTime(person.properties.expires_at) > toDateTime('2026-01-01')")

        expect(logic.values.actionValidationErrorsById[WAIT_NODE_ID]?.valid).toBe(true)
    })

    it('accepts a stored clock condition, and flags it once edited', async () => {
        // Grandfathered per condition, as the API is: a workflow saved before the rule existed
        // stays editable, but the condition itself has to meet the rule when it changes.
        await mountWith('now() >= toDateTime(person.properties.expires_at)')

        expect(logic.values.actionValidationErrorsById[WAIT_NODE_ID]?.valid).toBe(true)

        logic.actions.partialSetWorkflowActionConfig(WAIT_NODE_ID, {
            condition: conditionOn('now() >= toDateTime(person.properties.other_at)'),
        })

        expect(logic.values.actionValidationErrorsById[WAIT_NODE_ID]?.valid).toBe(false)
    })
})
