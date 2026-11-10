import { describe, expect, it } from 'vitest'

import { clientCredentialCandidates, ProviderNotConfiguredError } from '@/providers/client-credentials'
import type { ClientSecretKeys } from '@/providers/schema'
import type { Secret } from '@/types'

function steady(value: string): Secret {
    return { state: 'steady', value, versionId: 'v1', fetchedAt: 'now' }
}

// The shape of Bing Ads today: a migrated app whose old grants refresh only with the old credentials.
const KEYS: ClientSecretKeys = {
    clientId: 'BING_ADS_CLIENT_ID',
    clientSecret: 'BING_ADS_CLIENT_SECRET',
    fallbacks: [
        { clientId: 'BING_ADS_CLIENT_ID_FALLBACK', clientSecret: 'BING_ADS_CLIENT_SECRET_FALLBACK' },
        { clientSecret: 'BING_ADS_CLIENT_SECRET_OLDEST' },
    ],
}

const PRIMARY = { BING_ADS_CLIENT_ID: steady('id-new'), BING_ADS_CLIENT_SECRET: steady('secret-new') }

describe('client credential candidates', () => {
    it.each<[string, Record<string, Secret>, { clientId: string; clientSecret: string; source: string }[]]>([
        [
            'only the primary pair when no fallback secret is set',
            PRIMARY,
            [{ clientId: 'id-new', clientSecret: 'secret-new', source: 'primary' }],
        ],
        [
            'each fallback with a secret, in order',
            {
                ...PRIMARY,
                BING_ADS_CLIENT_ID_FALLBACK: steady('id-old'),
                BING_ADS_CLIENT_SECRET_FALLBACK: steady('secret-old'),
                BING_ADS_CLIENT_SECRET_OLDEST: steady('secret-oldest'),
            },
            [
                { clientId: 'id-new', clientSecret: 'secret-new', source: 'primary' },
                { clientId: 'id-old', clientSecret: 'secret-old', source: 'fallback' },
                { clientId: 'id-new', clientSecret: 'secret-oldest', source: 'fallback' },
            ],
        ],
        [
            'the primary id for a fallback whose id is unset',
            { ...PRIMARY, BING_ADS_CLIENT_SECRET_FALLBACK: steady('secret-old') },
            [
                { clientId: 'id-new', clientSecret: 'secret-new', source: 'primary' },
                { clientId: 'id-new', clientSecret: 'secret-old', source: 'fallback' },
            ],
        ],
        [
            'no fallback whose id is set but whose secret is empty',
            { ...PRIMARY, BING_ADS_CLIENT_ID_FALLBACK: steady('id-old'), BING_ADS_CLIENT_SECRET_FALLBACK: steady('') },
            [{ clientId: 'id-new', clientSecret: 'secret-new', source: 'primary' }],
        ],
        [
            // The staged value is not the live one, and Python reads only the live value.
            'the live value of a secret that is mid-rotation',
            {
                ...PRIMARY,
                BING_ADS_CLIENT_SECRET: {
                    state: 'rotating',
                    value: 'secret-new',
                    incoming: 'secret-next',
                    versionId: 'v2',
                    fetchedAt: 'now',
                },
            },
            [{ clientId: 'id-new', clientSecret: 'secret-new', source: 'primary' }],
        ],
    ])('returns %s', (_, secrets, expected) => {
        expect(clientCredentialCandidates('bing-ads', KEYS, secrets)).toEqual(expected)
    })

    it.each<[string, Record<string, Secret>]>([
        ['the client id is missing', { BING_ADS_CLIENT_SECRET: steady('secret-new') }],
        ['the client secret is missing', { BING_ADS_CLIENT_ID: steady('id-new') }],
        ['the client secret is empty', { ...PRIMARY, BING_ADS_CLIENT_SECRET: steady('') }],
        [
            'the client secret is in recovery',
            { ...PRIMARY, BING_ADS_CLIENT_SECRET: { state: 'recovery', versionId: 'v1', fetchedAt: 'now' } },
        ],
        // A fallback cannot stand in for a primary pair that is not configured.
        [
            'only a fallback is set',
            { BING_ADS_CLIENT_ID_FALLBACK: steady('id-old'), BING_ADS_CLIENT_SECRET_FALLBACK: steady('secret-old') },
        ],
    ])('says the app is not configured when %s', (_, secrets) => {
        expect(() => clientCredentialCandidates('bing-ads', KEYS, secrets)).toThrow(ProviderNotConfiguredError)
    })
})
