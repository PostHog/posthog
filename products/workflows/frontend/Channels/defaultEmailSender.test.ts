import { IntegrationType } from '~/types'

import { resolveDefaultEmailSender } from './defaultEmailSender'

const sender = (id: number, verified: boolean, kind = 'email'): IntegrationType =>
    ({ id, kind, config: { verified } }) as unknown as IntegrationType
const stopped = (id: number): IntegrationType =>
    ({ id, kind: 'email', config: { verified: true, ses_sending_status: 'failed' } }) as unknown as IntegrationType

describe('resolveDefaultEmailSender', () => {
    it.each([
        { case: 'the project default', integrations: [sender(1, true), sender(2, true)], defaultId: 2, expected: 2 },
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
        { case: 'nothing for an unverified default', integrations: [sender(1, false)], defaultId: 1, expected: null },
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
        {
            case: 'the only sender that can deliver when the default stopped sending',
            integrations: [stopped(1), sender(2, true)],
            defaultId: 1,
            expected: 2,
        },
        {
            case: 'the only sender that can deliver over a stopped one without a default',
            integrations: [stopped(1), sender(2, true)],
            defaultId: null,
            expected: 2,
        },
        {
            case: 'nothing when the only verified sender stopped sending',
            integrations: [stopped(1)],
            defaultId: 1,
            expected: null,
        },
        {
            case: 'nothing when the default stopped sending and several others can deliver',
            integrations: [stopped(1), sender(2, true), sender(3, true)],
            defaultId: 1,
            expected: null,
        },
    ])('picks $case', ({ integrations, defaultId, expected }) => {
        expect(resolveDefaultEmailSender(integrations, defaultId)?.integrationId ?? null).toEqual(expected)
    })
})
