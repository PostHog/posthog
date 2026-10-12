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
