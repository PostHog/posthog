import { GetSecretValueCommand, ResourceNotFoundException } from '@aws-sdk/client-secrets-manager'
import { describe, expect, it } from 'vitest'

import { createSecretsManagerStore } from '@/store/secretsManager.js'
import type { SecretStore } from '@/store/types.js'

const SECRET_ID = 'integration-service-secrets'

function fakeClient(fields: Record<string, unknown> | null, createdAt = new Date('2026-01-01T00:00:00Z')): any {
    return {
        send(command: unknown) {
            if (!(command instanceof GetSecretValueCommand)) {
                throw new Error('unexpected command')
            }
            if (fields === null) {
                throw new ResourceNotFoundException({ message: 'not found', $metadata: {} })
            }
            return Promise.resolve({
                SecretString: JSON.stringify(fields),
                VersionId: 'v-current',
                CreatedDate: createdAt,
            })
        },
    }
}

const store = (fields: Record<string, unknown> | null): SecretStore =>
    createSecretsManagerStore({ client: fakeClient(fields), secretId: SECRET_ID })

describe('secrets manager store', () => {
    it('reads every manifest credential out of the one secret', async () => {
        const snapshot = await store({
            HUBSPOT_APP_CLIENT_ID: 'id',
            HUBSPOT_APP_CLIENT_SECRET: 'sec',
            STRIPE_APP_SECRET_KEY: 'sk',
        }).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({ state: 'steady', value: 'sec' })
        expect(snapshot?.secrets['STRIPE_APP_SECRET_KEY']).toMatchObject({ state: 'steady', value: 'sk' })
    })

    it('reports steady and serves no previous when there is no fallback sibling', async () => {
        const snapshot = await store({ HUBSPOT_APP_CLIENT_SECRET: 'sec' }).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('steady')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).not.toHaveProperty('previous')
    })

    it('reports rotating with both values when a fallback sibling holds the outgoing one', async () => {
        const snapshot = await store({
            HUBSPOT_APP_CLIENT_SECRET: 'new',
            HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old',
        }).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({
            state: 'rotating',
            value: 'new',
            previous: 'old',
        })
    })

    it('takes the newest entry when the fallback list holds several', async () => {
        const snapshot = await store({
            HUBSPOT_APP_CLIENT_SECRET: 'new',
            HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old, older',
        }).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.previous).toBe('old')
    })

    it('reports steady when the fallback repeats the current value', async () => {
        const snapshot = await store({
            HUBSPOT_APP_CLIENT_SECRET: 'same',
            HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'same',
        }).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('steady')
    })

    // The reason rotation moved off AWS staging labels: with one shared secret, rotating
    // one credential must leave every other one alone.
    it('leaves other credentials steady while one is mid-rotation', async () => {
        const snapshot = await store({
            HUBSPOT_APP_CLIENT_SECRET: 'new',
            HUBSPOT_APP_CLIENT_SECRET_FALLBACKS: 'old',
            STRIPE_APP_SECRET_KEY: 'sk',
            GOOGLE_ADS_APP_CLIENT_SECRET: 'ga',
        }).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('rotating')
        expect(snapshot?.secrets['STRIPE_APP_SECRET_KEY']?.state).toBe('steady')
        expect(snapshot?.secrets['GOOGLE_ADS_APP_CLIENT_SECRET']?.state).toBe('steady')
    })

    it('serves no value at all for a field named in the recovery list', async () => {
        const snapshot = await store({
            HUBSPOT_APP_CLIENT_SECRET: 'burned',
            INTEGRATION_RECOVERY_KEYS: 'HUBSPOT_APP_CLIENT_SECRET',
        }).load()

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBeUndefined()
    })

    it('handles several fields in recovery from one comma-separated value', async () => {
        const snapshot = await store({
            STRIPE_APP_CLIENT_ID: 'id',
            STRIPE_APP_SECRET_KEY: 'burned',
            HUBSPOT_APP_CLIENT_SECRET: 'also-burned',
            INTEGRATION_RECOVERY_KEYS: 'STRIPE_APP_SECRET_KEY, HUBSPOT_APP_CLIENT_SECRET',
        }).load()

        expect(snapshot?.secrets['STRIPE_APP_SECRET_KEY']?.state).toBe('recovery')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(snapshot?.secrets['STRIPE_APP_CLIENT_ID']?.state).toBe('steady')
    })

    // Adding a credential has to be a reviewed code change, not just a secrets edit —
    // otherwise the provider manifest stops being a statement of what we hold. This also
    // keeps the signing keys sharing this secret from ever being served as credentials.
    it.each([
        ['an undeclared field', 'SOMETHING_UNDECLARED'],
        ['the recovery marker', 'INTEGRATION_RECOVERY_KEYS'],
        ['a caller signing key', 'CALLER_KEY_POSTHOG_DJANGO'],
        ['a fallback sibling', 'HUBSPOT_APP_CLIENT_SECRET_FALLBACKS'],
    ])('never exposes %s as a credential', async (_label, field) => {
        const snapshot = await store({
            HUBSPOT_APP_CLIENT_SECRET: 'sec',
            [field]: 'should-not-be-served',
        }).load()

        expect(snapshot?.secrets).not.toHaveProperty(field)
    })

    it('returns null when the secret does not exist in this environment', async () => {
        expect(await store(null).load()).toBeNull()
    })
})
