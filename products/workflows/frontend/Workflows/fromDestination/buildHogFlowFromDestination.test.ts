import { HogFunctionTemplateType } from '~/types'

import { EXIT_NODE_ID, TRIGGER_NODE_ID } from '../workflowLogic'
import { buildHogFlowFromDestination } from './buildHogFlowFromDestination'

const TEMPLATE = {
    id: 'template-slack',
    type: 'destination',
    name: 'Slack',
    description: 'Sends a message to a Slack channel',
    status: 'stable',
    free: true,
    code: '',
    code_language: 'hog',
    inputs_schema: [],
} as unknown as HogFunctionTemplateType

describe('buildHogFlowFromDestination', () => {
    it('wires the trigger, the template step and the exit into a linear draft without server-owned fields', () => {
        const triggerFilters = { events: [{ id: '$pageview', type: 'events' }], filter_test_accounts: true }
        const inputs = { text: { value: 'A new pageview' } }

        const { workflow, functionActionId } = buildHogFlowFromDestination({
            template: TEMPLATE,
            name: 'Slack notification',
            triggerFilters,
            inputs,
        })

        expect(workflow).toMatchObject({ name: 'Slack notification', status: 'draft' })
        expect(workflow).not.toHaveProperty('id')
        expect(workflow).not.toHaveProperty('team_id')
        expect(workflow.actions?.map((action) => [action.id, action.type])).toEqual([
            [TRIGGER_NODE_ID, 'trigger'],
            [functionActionId, 'function'],
            [EXIT_NODE_ID, 'exit'],
        ])
        expect(workflow.actions?.[0].config).toEqual({ type: 'event', filters: triggerFilters })
        expect(workflow.actions?.[1].config).toEqual({ template_id: 'template-slack', inputs })
        expect(workflow.edges).toEqual([
            { from: TRIGGER_NODE_ID, to: functionActionId, type: 'continue' },
            { from: functionActionId, to: EXIT_NODE_ID, type: 'continue' },
        ])
    })
})
