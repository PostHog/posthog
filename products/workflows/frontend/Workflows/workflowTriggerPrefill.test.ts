import type { HogFlow } from './hogflows/types'
import {
    type WorkflowTriggerConfig,
    applyEmailScaffold,
    applyTriggerPrefill,
    parseWorkflowScaffold,
    parseWorkflowTriggerPrefill,
    serializeWorkflowTriggerPrefill,
} from './workflowTriggerPrefill'

describe('workflowTriggerPrefill', () => {
    const config: WorkflowTriggerConfig = {
        type: 'batch',
        filters: { properties: [{ key: 'id', type: 'cohort', value: 7, operator: 'in' }] },
    }

    it('round-trips a trigger config through serialize and parse', () => {
        expect(parseWorkflowTriggerPrefill(serializeWorkflowTriggerPrefill(config))).toEqual(config)
    })

    it.each([
        ['nothing', undefined],
        ['a non-JSON string', 'not-json'],
        ['an unknown trigger type', '{"type":"nonsense"}'],
        ['a batch trigger missing its filters', '{"type":"batch"}'],
    ])('returns null for %s', (_label, raw) => {
        expect(parseWorkflowTriggerPrefill(raw)).toBeNull()
    })

    it('parses the email scaffold and rejects unknown scaffolds', () => {
        expect(parseWorkflowScaffold('email')).toBe('email')
        expect(parseWorkflowScaffold('nonsense')).toBeNull()
        expect(parseWorkflowScaffold(undefined)).toBeNull()
    })

    it('applyTriggerPrefill replaces only the trigger action config', () => {
        const workflow = {
            actions: [
                { id: 'trigger_node', type: 'trigger', config: { type: 'event', filters: {} } },
                { id: 'exit_node', type: 'exit', config: { reason: 'Default exit' } },
            ],
        } as HogFlow

        const result = applyTriggerPrefill(workflow, config)

        expect(result.actions[0].config).toEqual(config)
        expect(result.actions[1]).toEqual(workflow.actions[1])
    })

    it('applyEmailScaffold wires an email step between the trigger and the exit', () => {
        const workflow = {
            actions: [
                { id: 'trigger_node', type: 'trigger' },
                { id: 'exit_node', type: 'exit' },
            ],
            edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
        } as HogFlow

        const scaffolded = applyEmailScaffold(workflow, { subject: { value: 'Hi' } })

        const emailAction = scaffolded.actions.find((action) => action.type === 'function_email')
        expect(emailAction?.config).toEqual({ template_id: 'template-email', inputs: { subject: { value: 'Hi' } } })
        expect(scaffolded.edges).toEqual([
            { from: 'trigger_node', to: emailAction?.id, type: 'continue' },
            { from: emailAction?.id, to: 'exit_node', type: 'continue' },
        ])
    })
})
