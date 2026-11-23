import type { IntegrationType } from '~/types'

import type { HogFlow, HogFlowAction } from './hogflows/types'
import { StoppedSenderSteps, stepToChange, stoppedSenderMessage, stoppedSenderSteps } from './stoppedSenderSteps'

const sender = (id: number, domain: string, stopped: boolean): IntegrationType =>
    ({
        id,
        kind: 'email',
        config: {
            email: `hello@${domain}`,
            domain,
            verified: true,
            ...(stopped ? { ses_sending_status: 'failed' } : {}),
        },
    }) as unknown as IntegrationType

const SENDERS = [sender(1, 'ok.example.com', false), sender(2, 'a.example.com', true), sender(3, 'b.example.com', true)]

const ownStep = (id: string, from: Record<string, unknown>): HogFlowAction =>
    ({ id, type: 'function_email', config: { inputs: { email: { value: { from } } } } }) as unknown as HogFlowAction

const olderEmailStep = (id: string, from: Record<string, unknown>): HogFlowAction =>
    ({
        id,
        type: 'function',
        config: { template_id: 'template-email', inputs: { email: { value: { from } } } },
    }) as unknown as HogFlowAction

const sandboxStep = (id: string): HogFlowAction =>
    ({ id, type: 'email_sandbox', config: {} }) as unknown as HogFlowAction

const workflow = (...actions: HogFlowAction[]): Pick<HogFlow, 'actions'> => ({ actions })

describe('stoppedSenderSteps', () => {
    it.each<[string, Pick<HogFlow, 'actions'> | null, IntegrationType[] | null, ReturnType<typeof stoppedSenderSteps>]>(
        [
            ['a step on a sender that still sends', workflow(ownStep('s1', { integrationId: 1 })), SENDERS, null],
            ['senders not loaded yet', workflow(ownStep('s1', { integrationId: 2 })), null, null],
            ['no saved workflow', null, SENDERS, null],
            ['a test sender step', workflow(sandboxStep('s1')), SENDERS, null],
            [
                'a step on a stopped sender',
                workflow(ownStep('s1', { integrationId: 1 }), ownStep('s2', { integrationId: 2 })),
                SENDERS,
                { domains: ['a.example.com'], senderId: 2, stepIds: ['s2'] },
            ],
            [
                'an older email step saved as a function step',
                workflow(olderEmailStep('s1', { integrationId: 2 })),
                SENDERS,
                { domains: ['a.example.com'], senderId: 2, stepIds: ['s1'] },
            ],
            [
                'a delay step that kept an email config',
                workflow({
                    id: 's1',
                    type: 'delay',
                    config: {
                        template_id: 'template-email',
                        inputs: { email: { value: { from: { integrationId: 2 } } } },
                    },
                } as unknown as HogFlowAction),
                SENDERS,
                null,
            ],
            [
                'a step whose rotation list is not a list',
                workflow(ownStep('s1', { integrationIds: '2' }), ownStep('s2', { integrationId: 3 })),
                SENDERS,
                { domains: ['b.example.com'], senderId: 3, stepIds: ['s2'] },
            ],
            [
                'a step whose rotation list holds something other than sender IDs',
                workflow(ownStep('s1', { integrationIds: ['3'], integrationId: 2 })),
                SENDERS,
                null,
            ],
            [
                'a rotating step without its own sender ID',
                workflow(ownStep('s1', { integrationIds: [2] })),
                SENDERS,
                null,
            ],
            [
                'a rotating step with one stopped sender, and two stopped domains',
                workflow(
                    ownStep('s1', { integrationId: 1, integrationIds: [1, 3] }),
                    ownStep('s2', { integrationId: 2 })
                ),
                SENDERS,
                { domains: ['b.example.com', 'a.example.com'], senderId: 3, stepIds: ['s1', 's2'] },
            ],
        ]
    )('for %s', (_, flow, integrations, expected) => {
        expect(stoppedSenderSteps(flow, integrations)).toEqual(expected)
    })

    it.each<[string, Pick<HogFlow, 'actions'>, string | null]>([
        ['the first broken step the draft still has', workflow(ownStep('b', { integrationId: 2 })), 'b'],
        [
            'a later broken step when the draft moved an earlier one to a sender that sends',
            workflow(ownStep('a', { integrationId: 1 }), ownStep('b', { integrationId: 3 })),
            'b',
        ],
        ['no step when the draft fixed every broken step', workflow(ownStep('a', { integrationId: 1 })), null],
    ])('opens %s', (_, draft, expected) => {
        const broken = { domains: ['a.example.com'], senderId: 2, stepIds: ['a', 'b'] }
        expect(stepToChange(broken, draft, SENDERS)).toEqual(expected)
    })

    it.each<[string, StoppedSenderSteps, string]>([
        [
            'one step on one domain',
            { domains: ['a.example.com'], senderId: 2, stepIds: ['a'] },
            "Sending stopped for a.example.com. An email step in this workflow sends from it, and those emails fail until the domain's DNS records are fixed. Fix your sending domain, or change the sender on that step.",
        ],
        [
            'several steps on several domains',
            { domains: ['a.example.com', 'b.example.com'], senderId: 2, stepIds: ['a', 'b'] },
            "Sending stopped for a.example.com, b.example.com. 2 email steps in this workflow send from them, and those emails fail until the domains' DNS records are fixed. Fix your sending domain, or change the sender on those steps.",
        ],
    ])('says what stopped for %s', (_, broken, expected) => {
        expect(stoppedSenderMessage(broken)).toEqual(expected)
    })
})
