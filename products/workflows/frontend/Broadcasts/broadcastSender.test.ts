import type { IntegrationType } from '~/types'

import { getSenderLaunchError } from './broadcastWizardLogic'

const sender = (id: number, verified: boolean): IntegrationType =>
    ({ id, kind: 'email', display_name: `sender-${id}`, config: { verified } }) as unknown as IntegrationType

describe('getSenderLaunchError', () => {
    it.each([
        ['no sender chosen yet', undefined, [sender(1, true)], null],
        ['a verified sender', 1, [sender(1, true)], null],
        ['an unverified sender', 1, [sender(1, false)], "Verify the sender's domain before sending"],
        ['senders still loading', 1, null, 'Checking the email sender. Try again in a moment.'],
        [
            'a sender that was deleted',
            7,
            [sender(1, true)],
            'The chosen email sender no longer exists. Pick another one on the content step.',
        ],
    ])('blocks launch for %s: %s', (_, integrationId, integrations, expected) => {
        expect(getSenderLaunchError(integrationId, integrations)).toBe(expected)
    })
})
