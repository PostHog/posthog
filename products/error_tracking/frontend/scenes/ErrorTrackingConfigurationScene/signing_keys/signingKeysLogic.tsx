import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ErrorTrackingSigningKey } from 'lib/components/Errors/types'

import type { signingKeysLogicType } from './signingKeysLogicType'

export const signingKeysLogic = kea<signingKeysLogicType>([
    path([
        'products',
        'error_tracking',
        'scenes',
        'ErrorTrackingConfigurationScene',
        'signing_keys',
        'signingKeysLogic',
    ]),

    actions({
        setModalOpen: (open: boolean) => ({ open }),
        setLabel: (label: string) => ({ label }),
        setPublicKey: (publicKey: string) => ({ publicKey }),
    }),

    reducers({
        modalOpen: [false, { setModalOpen: (_, { open }) => open }],
        label: ['', { setLabel: (_, { label }) => label, setModalOpen: () => '' }],
        publicKey: ['', { setPublicKey: (_, { publicKey }) => publicKey, setModalOpen: () => '' }],
    }),

    loaders(({ values, actions }) => ({
        signingKeys: [
            [] as ErrorTrackingSigningKey[],
            {
                loadSigningKeys: async () => {
                    const res = await api.errorTracking.signingKeys.list()
                    return res.results
                },
                createSigningKey: async () => {
                    const key = await api.errorTracking.signingKeys.create({
                        label: values.label.trim() || undefined,
                        public_key: values.publicKey.trim(),
                    })
                    lemonToast.success(`Signing key ${key.key_id} added`)
                    actions.setModalOpen(false)
                    return [key, ...values.signingKeys]
                },
                revokeSigningKey: async (id: string) => {
                    const updated = await api.errorTracking.signingKeys.revoke(id)
                    lemonToast.success('Signing key revoked')
                    return values.signingKeys.map((k) => (k.id === id ? updated : k))
                },
            },
        ],
    })),

    listeners(() => ({
        createSigningKeyFailure: ({ error }) => {
            // Surface the API's validation message (e.g. "Public key must be an Ed25519 key.").
            // The modal stays open with its input intact, since the loader threw before closing it.
            const detail = (error as { detail?: string; data?: { public_key?: string[] } }) ?? {}
            lemonToast.error(detail.detail || detail.data?.public_key?.[0] || 'Could not add signing key')
        },
    })),

    afterMount(({ actions }) => actions.loadSigningKeys()),
])
