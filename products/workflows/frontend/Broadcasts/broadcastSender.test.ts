import type { IntegrationType } from '~/types'

import {
    DELETED_SENDER_ERROR,
    SANDBOX_SENDER_BROADCAST_ERROR,
    SENDERS_LOAD_FAILED_ERROR,
    getPickerSenderIds,
    getSenderLaunchError,
} from './broadcastWizardLogic'

const sender = (id: number, verified: boolean, provider = 'ses'): IntegrationType => ({
    id,
    kind: 'email',
    display_name: `sender-${id}`,
    icon_url: '',
    config: { verified, provider },
    created_at: '2026-01-01T00:00:00Z',
})

describe('broadcast senders', () => {
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
        ['the sandbox sender', 3, [sender(3, true, 'sandbox')], false, SANDBOX_SENDER_BROADCAST_ERROR],
        [
            'the sandbox sender in the rotation',
            [1, 3],
            [sender(1, true), sender(3, true, 'sandbox')],
            false,
            SANDBOX_SENDER_BROADCAST_ERROR,
        ],
    ])('blocks launch for %s', (_, ids, integrations, integrationsLoading, expected) => {
        const from = Array.isArray(ids) ? { integrationId: ids[0], integrationIds: ids } : { integrationId: ids }
        expect(getSenderLaunchError(from, integrations, integrationsLoading)).toBe(expected)
    })

    it.each([
        ['own senders', [1, 2], [sender(1, true), sender(2, true)], [1, 2]],
        ['a deleted sender in the rotation', [1, 7], [sender(1, true)], [1]],
        ['the sandbox sender', [3], [sender(3, true, 'sandbox')], []],
        ['the sandbox sender in the rotation', [1, 3], [sender(1, true), sender(3, true, 'sandbox')], []],
        ['senders not loaded yet', [1, 3], null, [1, 3]],
    ])('shows the picker the right senders for %s', (_, ids, integrations, expected) => {
        const from = { integrationId: ids[0], integrationIds: ids.length > 1 ? ids : undefined }
        expect(getPickerSenderIds(from, integrations)).toEqual(expected)
    })
})
