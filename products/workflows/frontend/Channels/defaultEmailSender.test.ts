import { IntegrationType } from '~/types'

import { resolveDefaultEmailSender } from './defaultEmailSender'

const sender = (id: number, verified: boolean, kind = 'email'): IntegrationType =>
    ({ id, kind, config: { verified } }) as unknown as IntegrationType

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
    ])('picks $case', ({ integrations, defaultId, expected }) => {
        expect(resolveDefaultEmailSender(integrations, defaultId)?.integrationId ?? null).toEqual(expected)
    })
})
