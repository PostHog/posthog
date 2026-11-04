import { IntegrationType } from '~/types'

import type { HogFlowAction } from '../Workflows/hogflows/types'
import { allowsSandboxSender, resolveDefaultEmailSender } from './defaultEmailSender'

const sender = (id: number, verified: boolean, kind = 'email'): IntegrationType =>
    ({ id, kind, config: { verified } }) as unknown as IntegrationType

const sandboxSender = { ...sender(7, true), config: { verified: true, provider: 'sandbox' } }

describe('defaultEmailSender', () => {
    describe('resolveDefaultEmailSender', () => {
        it.each([
            {
                case: 'nothing when only sandbox exists',
                integrations: [sandboxSender],
                defaultId: null,
                expected: null,
            },
            {
                case: 'the own sender beside sandbox',
                integrations: [sandboxSender, sender(1, true)],
                defaultId: null,
                expected: 1,
            },
            { case: 'nothing for a sandbox default', integrations: [sandboxSender], defaultId: 7, expected: null },
            {
                case: 'the project default',
                integrations: [sender(1, true), sender(2, true)],
                defaultId: 2,
                expected: 2,
            },
            {
                case: 'the only verified sender',
                integrations: [sender(1, true), sender(2, false)],
                defaultId: null,
                expected: 1,
            },
            {
                case: 'nothing when several are verified',
                integrations: [sender(1, true), sender(2, true)],
                defaultId: null,
                expected: null,
            },
            {
                case: 'nothing for an unverified default',
                integrations: [sender(1, false)],
                defaultId: 1,
                expected: null,
            },
            {
                case: 'the only verified sender when the default was deleted',
                integrations: [sender(1, true)],
                defaultId: 9,
                expected: 1,
            },
            {
                case: 'nothing for a verified non-email integration',
                integrations: [sender(1, true, 'slack')],
                defaultId: 1,
                expected: null,
            },
        ])('picks $case', ({ integrations, defaultId, expected }) => {
            expect(resolveDefaultEmailSender(integrations, defaultId)?.integrationId ?? null).toEqual(expected)
        })
    })

    describe('allowsSandboxSender', () => {
        it.each<{ step: string; actionType: HogFlowAction['type']; originProduct: string | null; expected: boolean }>([
            { step: 'a workflow email step', actionType: 'function_email', originProduct: null, expected: true },
            {
                step: 'a broadcast email step',
                actionType: 'function_email',
                originProduct: 'broadcasts',
                expected: false,
            },
            { step: 'a generic function step', actionType: 'function', originProduct: null, expected: false },
            { step: 'a trigger', actionType: 'trigger', originProduct: null, expected: false },
        ])('is $expected for $step', ({ actionType, originProduct, expected }) => {
            expect(allowsSandboxSender(actionType, originProduct)).toBe(expected)
        })
    })
})
