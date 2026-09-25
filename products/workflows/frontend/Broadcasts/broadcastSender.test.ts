import type { IntegrationType } from '~/types'

import { SENDERS_LOAD_FAILED_ERROR, getSenderLaunchError } from './broadcastWizardLogic'

const sender = (id: number, verified: boolean): IntegrationType => ({
    id,
    kind: 'email',
    display_name: `sender-${id}`,
    icon_url: '',
    config: { verified },
    created_at: '2026-01-01T00:00:00Z',
})

describe('getSenderLaunchError', () => {
    it.each([
        ['no sender chosen yet', undefined, [sender(1, true)], false, null],
        ['a verified sender', 1, [sender(1, true)], false, null],
        ['an unverified sender', 1, [sender(1, false)], false, "Verify the sender's domain before sending"],
        ['senders still loading', 1, null, true, 'Checking the email sender. Try again in a moment.'],
        ['senders failed to load', 1, null, false, SENDERS_LOAD_FAILED_ERROR],
        [
            'a sender that was deleted',
            7,
            [sender(1, true)],
            false,
            'The chosen email sender no longer exists. Pick another one on the content step.',
        ],
    ])('blocks launch for %s', (_, integrationId, integrations, integrationsLoading, expected) => {
        expect(getSenderLaunchError(integrationId, integrations, integrationsLoading)).toBe(expected)
    })
})
