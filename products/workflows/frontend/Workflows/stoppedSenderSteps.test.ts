import type { IntegrationType } from '~/types'

import type { HogFlow, HogFlowAction } from './hogflows/types'
import {
    StoppedSenderSteps,
    changeSenderAdvice,
    repairTarget,
    stoppedSenderMessage,
    stoppedSenderSteps,
} from './stoppedSenderSteps'

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

    const LIVE = workflow(
        olderEmailStep('older', { integrationId: 2 }),
        ownStep('a', { integrationId: 2 }),
        ownStep('welcome.email', { integrationId: 3 })
    )
    const BROKEN = stoppedSenderSteps(LIVE, SENDERS)!

    it.each<[string, Pick<HogFlow, 'actions'>, ReturnType<typeof repairTarget>]>([
        [
            'the first broken step, without the test sender for an older step',
            LIVE,
            { stepId: 'older', testSenderTakesSteps: false },
        ],
        [
            'a step the draft still has broken, with the test sender once the draft drops the others',
            workflow(ownStep('a', { integrationId: 2 }), ownStep('welcome.email', { integrationId: 1 })),
            { stepId: 'a', testSenderTakesSteps: true },
        ],
        [
            'a later step when the draft fixed the earlier ones, without the test sender for its ID',
            workflow(ownStep('a', { integrationId: 1 }), ownStep('welcome.email', { integrationId: 3 })),
            { stepId: 'welcome.email', testSenderTakesSteps: false },
        ],
        [
            'no step when the draft fixed every broken step, with advice for the saved steps',
            workflow(ownStep('a', { integrationId: 1 })),
            { stepId: null, testSenderTakesSteps: false },
        ],
    ])('targets %s', (_, draft, expected) => {
        expect(repairTarget(BROKEN, LIVE, draft, SENDERS)).toEqual(expected)
    })

    it.each<[string, StoppedSenderSteps, string]>([
        [
            'one step on one domain',
            { domains: ['a.example.com'], senderId: 2, stepIds: ['a'] },
            "Sending stopped for a.example.com. An email step in this workflow sends from it, and those emails fail until the domain's DNS records are fixed. Fix your sending domain, or do this.",
        ],
        [
            'several steps on several domains',
            { domains: ['a.example.com', 'b.example.com'], senderId: 2, stepIds: ['a', 'b'] },
            "Sending stopped for a.example.com, b.example.com. 2 email steps in this workflow send from them, and those emails fail until the domains' DNS records are fixed. Fix your sending domain, or do this.",
        ],
    ])('says what stopped for %s', (_, broken, expected) => {
        expect(stoppedSenderMessage(broken, 'do this')).toEqual(expected)
    })

    it.each<[number, boolean, boolean, string]>([
        [1, true, true, 'change the sender on that step to another sender'],
        [
            2,
            false,
            true,
            'switch those steps to the PostHog test sender, which reaches only verified members of your organization',
        ],
        [1, false, false, 'add another sender and switch that step to it'],
    ])('advises %i step(s) with another sender %s and the test sender %s', (count, other, testSender, expected) => {
        expect(changeSenderAdvice(count, other, testSender)).toEqual(expected)
    })
})
