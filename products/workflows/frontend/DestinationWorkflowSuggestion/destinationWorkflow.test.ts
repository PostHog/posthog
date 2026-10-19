import { HogFunctionTemplateType } from '~/types'

import { HogFlowActionSchema } from '../Workflows/hogflows/steps/types'
import { DESTINATION_STEP_ID, buildDestinationWorkflow } from './destinationWorkflow'

const TEMPLATE = {
    id: 'template-customerio',
    type: 'destination',
    name: 'Customer.io',
    description: 'Identify or track events and people in Customer.io',
    status: 'stable',
    free: false,
    code: '',
    code_language: 'hog',
    inputs_schema: [
        { key: 'site_id', type: 'string', label: 'Site ID', secret: false, required: true },
        { key: 'action', type: 'choice', label: 'Action', secret: false, required: true, default: 'automatic' },
    ],
} as unknown as HogFunctionTemplateType

describe('destinationWorkflow', () => {
    it('builds a draft that runs the template between the trigger and the exit, with its default inputs', () => {
        const workflow = buildDestinationWorkflow(TEMPLATE)

        expect(workflow).toMatchObject({ name: 'Customer.io workflow', status: 'draft' })
        expect(workflow.actions.map((action) => HogFlowActionSchema.safeParse(action).success)).toEqual([
            true,
            true,
            true,
        ])
        expect(workflow.actions.map((action) => action.type)).toEqual(['trigger', 'function', 'exit'])
        expect(workflow.edges?.map(({ from, to }) => [from, to])).toEqual([
            ['trigger_node', DESTINATION_STEP_ID],
            [DESTINATION_STEP_ID, 'exit_node'],
        ])
        expect(workflow.actions[1].config).toEqual({
            template_id: 'template-customerio',
            inputs: { action: { value: 'automatic' } },
        })
    })
})
