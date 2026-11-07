import { draftMessage } from '../MessageAudience/messageDrafts'
import type { HogFlowAction } from './hogflows/types'
import { allowsSandboxSender, prefilledWorkflow, withEmailSender } from './workflowEmailPrefill'
import { NEW_WORKFLOW } from './workflowLogic'
import type { WorkflowTriggerConfig } from './workflowTriggerPrefill'

const EVENT_TRIGGER: WorkflowTriggerConfig = {
    type: 'event',
    filters: { events: [{ id: '$exception', name: '$exception', type: 'events' }] },
}
const BATCH_TRIGGER: WorkflowTriggerConfig = { type: 'batch', filters: { properties: [] } }

describe('workflowEmailPrefill', () => {
    it.each([
        {
            trigger: 'an event trigger',
            config: EVENT_TRIGGER,
            masking: { hash: '{person.id}', ttl: null, threshold: null },
        },
        { trigger: 'a batch trigger', config: BATCH_TRIGGER, masking: undefined },
    ])('opens $trigger with a draft email as trigger, email, exit', ({ config, masking }) => {
        const workflow = prefilledWorkflow(NEW_WORKFLOW, config, draftMessage({ kind: 'issue_hit' }))

        expect(workflow.actions.map((action) => action.type)).toEqual(['trigger', 'function_email', 'exit'])
        expect(workflow.edges.map(({ from, to }) => [from, to])).toEqual([
            ['trigger_node', 'action_function_email_prefilled'],
            ['action_function_email_prefilled', 'exit_node'],
        ])
        expect((workflow.actions[1].config as any).inputs.email.value).toMatchObject({
            to: { email: '{{ person.properties.email }}' },
            subject: 'Sorry about the error you ran into',
        })
        expect(workflow.trigger_masking).toEqual(masking)
    })

    it('keeps a sender the email step already has and fills the ones without', () => {
        const workflow = prefilledWorkflow(NEW_WORKFLOW, EVENT_TRIGGER, draftMessage({ kind: 'issue_hit' }))
        const filled = withEmailSender(workflow, 5)
        const refilled = withEmailSender(filled.workflow, 9)

        expect(filled.filled).toBe(true)
        expect((filled.workflow.actions[1].config as any).inputs.email.value.from).toEqual({ integrationId: 5 })
        expect(refilled).toEqual({ workflow: filled.workflow, filled: false })
    })

    it.each<{ step: string; actionType: HogFlowAction['type']; originProduct: string | null; expected: boolean }>([
        { step: 'a workflow email step', actionType: 'function_email', originProduct: null, expected: true },
        {
            step: 'a broadcast email step',
            actionType: 'function_email',
            originProduct: 'broadcasts',
            expected: false,
        },
        {
            step: 'a transactional email key step',
            actionType: 'function_email',
            originProduct: 'transactional_email_keys',
            expected: false,
        },
        { step: 'a loops email step', actionType: 'function_email', originProduct: 'loops', expected: false },
        { step: 'a generic function step', actionType: 'function', originProduct: null, expected: false },
        { step: 'a trigger', actionType: 'trigger', originProduct: null, expected: false },
    ])('allows the sandbox sender for $step: $expected', ({ actionType, originProduct, expected }) => {
        expect(allowsSandboxSender(actionType, originProduct)).toBe(expected)
    })
})
