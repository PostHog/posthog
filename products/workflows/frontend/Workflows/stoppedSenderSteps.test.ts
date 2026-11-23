import type { IntegrationType } from '~/types'

import type { HogFlow, HogFlowAction } from './hogflows/types'
import { changeSenderAdvice, stoppedSenderSteps } from './stoppedSenderSteps'

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
                'a rotating step with one stopped sender, and two stopped domains',
                workflow(ownStep('s1', { integrationIds: [1, 3] }), ownStep('s2', { integrationId: 2 })),
                SENDERS,
                { domains: ['b.example.com', 'a.example.com'], senderId: 3, stepIds: ['s1', 's2'] },
            ],
        ]
    )('for %s', (_, flow, integrations, expected) => {
        expect(stoppedSenderSteps(flow, integrations)).toEqual(expected)
    })

    it.each<[number, boolean, boolean, string]>([
        [1, true, true, 'change the sender on that step to another sender'],
        [2, false, true, 'switch those steps to the PostHog test sender'],
        [1, false, false, 'add another sender and switch that step to it'],
    ])('advises %i step(s) with another sender %s and the test sender %s', (count, other, testSender, expected) => {
        expect(changeSenderAdvice(count, other, testSender)).toEqual(expected)
    })
})
