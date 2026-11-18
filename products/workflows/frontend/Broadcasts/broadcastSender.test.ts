import type { IntegrationType } from '~/types'

import { DELETED_SENDER_ERROR, SENDERS_LOAD_FAILED_ERROR, getSenderLaunchError } from './broadcastWizardLogic'

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
        ['a sender that was deleted', 7, [sender(1, true)], false, DELETED_SENDER_ERROR],
        ['a deleted sender in the rotation', [1, 7], [sender(1, true)], false, DELETED_SENDER_ERROR],
        [
            'an unverified sender in the rotation',
            [1, 2],
            [sender(1, true), sender(2, false)],
            false,
            "Verify the sender's domain before sending",
        ],
        ['a verified rotation', [1, 2], [sender(1, true), sender(2, true)], false, null],
    ])('blocks launch for %s', (_, ids, integrations, integrationsLoading, expected) => {
        const from = Array.isArray(ids) ? { integrationId: ids[0], integrationIds: ids } : { integrationId: ids }
        expect(getSenderLaunchError(from, integrations, integrationsLoading)).toBe(expected)
    })
})
