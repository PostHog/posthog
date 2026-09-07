import type { HogFlow } from './hogflows/types'
import {
    SCAFFOLD_PREFILL_PARAM,
    TRIGGER_PREFILL_PARAM,
    type WorkflowTriggerConfig,
    applyEmailScaffold,
    parseWorkflowScaffold,
    parseWorkflowTriggerPrefill,
    urlForNewWorkflowWithTrigger,
    urlForWorkflowChooserWithTrigger,
} from './workflowTriggerPrefill'

describe('workflowTriggerPrefill', () => {
    const config: WorkflowTriggerConfig = {
        type: 'batch',
        filters: { properties: [{ key: 'id', type: 'cohort', value: 7, operator: 'in' }] },
    }

    it('round-trips a trigger config through the URL', () => {
        const url = urlForNewWorkflowWithTrigger(config)
        const raw = new URLSearchParams(url.split('?')[1]).get(TRIGGER_PREFILL_PARAM)

        expect(parseWorkflowTriggerPrefill(raw ?? undefined)).toEqual(config)
    })

    it.each([
        ['nothing', undefined],
        ['a non-JSON string', 'not-json'],
        ['an unknown trigger type', '{"type":"nonsense"}'],
        ['a batch trigger missing its filters', '{"type":"batch"}'],
    ])('returns null for %s', (_label, raw) => {
        expect(parseWorkflowTriggerPrefill(raw)).toBeNull()
    })

    it('urlForWorkflowChooserWithTrigger opens the chooser modal with the prefill params attached', () => {
        const url = urlForWorkflowChooserWithTrigger(config, 'email')
        const [path, rest] = url.split('?')
        const [search, hash] = rest.split('#')
        const params = new URLSearchParams(search)

        expect(path).toBe('/workflows')
        expect(hash).toContain('newWorkflow')
        expect(parseWorkflowTriggerPrefill(params.get(TRIGGER_PREFILL_PARAM) ?? undefined)).toEqual(config)
        expect(params.get(SCAFFOLD_PREFILL_PARAM)).toBe('email')
    })

    it('round-trips the email scaffold through the URL and rejects unknown scaffolds', () => {
        const url = urlForNewWorkflowWithTrigger(config, 'email')
        const raw = new URLSearchParams(url.split('?')[1]).get(SCAFFOLD_PREFILL_PARAM)

        expect(parseWorkflowScaffold(raw ?? undefined)).toBe('email')
        expect(parseWorkflowScaffold('nonsense')).toBeNull()
        expect(parseWorkflowScaffold(undefined)).toBeNull()
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
