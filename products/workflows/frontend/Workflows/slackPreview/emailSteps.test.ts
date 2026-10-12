import type { HogFlow } from '../hogflows/types'
import { listEmailSteps } from './emailSteps'

const workflowSendingFrom = (from: unknown): HogFlow =>
    ({
        name: 'Onboarding drip',
        actions: [
            { id: 'trigger', name: 'Trigger', type: 'trigger', config: { type: 'event' } },
            {
                id: 'mail',
                name: 'Welcome',
                type: 'function_email',
                config: { inputs: { email: { value: { subject: 'Hi', from, html: '<p>Hi</p>' } } } },
            },
        ],
        edges: [{ from: 'trigger', to: 'mail', type: 'continue' }],
    }) as unknown as HogFlow

describe('listEmailSteps', () => {
    it('lists the emails the trigger reaches in the order a contact runs through them', () => {
        const email = (id: string): Record<string, unknown> => ({
            id,
            name: id,
            type: 'function_email',
            config: { inputs: { email: { value: { subject: id } } } },
        })
        const workflow = {
            actions: [
                email('unreachable'),
                email('after_split'),
                email('second_branch'),
                email('first_branch'),
                { id: 'split', name: 'Split', type: 'conditional_branch', config: {} },
                { id: 'trigger', name: 'Trigger', type: 'trigger', config: { type: 'event' } },
            ],
            edges: [
                { from: 'trigger', to: 'split', type: 'continue' },
                { from: 'split', to: 'after_split', type: 'continue' },
                { from: 'split', to: 'second_branch', type: 'branch', index: 1 },
                { from: 'split', to: 'first_branch', type: 'branch', index: 0 },
            ],
        } as unknown as HogFlow

        expect(listEmailSteps(workflow).map((step) => step.actionId)).toEqual([
            'first_branch',
            'second_branch',
            'after_split',
        ])
    })

    it.each([
        ['the connected sender', { integrationId: 7 }, 'Hedgebox team <hello@example.com>'],
        ['a blank sender override', { integrationId: 7, email: '', name: '' }, 'Hedgebox team <hello@example.com>'],
        ['an overridden sender name', { integrationId: 7, email: '', name: 'Support' }, 'Support <hello@example.com>'],
        ['a sender name without an address', { name: 'Support' }, 'Support'],
        ['a plain template string', '{{ person.properties.owner }}', '{{ person.properties.owner }}'],
    ])('shows %s as the email sender', (_name, from, expected) => {
        const steps = listEmailSteps(workflowSendingFrom(from), {
            7: { name: 'Hedgebox team', email: 'hello@example.com' },
        })

        expect(steps.map((step) => [step.actionId, step.from])).toEqual([['mail', expected]])
    })
})
