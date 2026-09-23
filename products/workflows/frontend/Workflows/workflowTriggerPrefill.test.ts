import {
    TRIGGER_PREFILL_PARAM,
    type WorkflowTriggerConfig,
    parseWorkflowTriggerPrefill,
    urlForNewWorkflowWithTrigger,
} from './workflowTriggerPrefill'

describe('workflowTriggerPrefill', () => {
    it('round-trips a trigger config through the URL', () => {
        const config: WorkflowTriggerConfig = {
            type: 'batch',
            filters: { properties: [{ key: 'id', type: 'cohort', value: 7, operator: 'in' }] },
        }

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
})
