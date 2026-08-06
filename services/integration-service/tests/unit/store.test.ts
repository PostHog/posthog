import { GetSecretValueCommand, ResourceNotFoundException } from '@aws-sdk/client-secrets-manager'
import { describe, expect, it } from 'vitest'

import { createSecretsManagerStore } from '@/store/secretsManager.js'

// AWSCURRENT/AWSPREVIOUS pairs, keyed by secret id. `undefined` for a stage means the
// stage does not exist, which is how a never-rotated secret actually looks.
type Versions = Record<string, { current?: unknown; previous?: unknown }>

function fakeClient(versions: Versions, createdAt = new Date('2026-01-01T00:00:00Z')): any {
    return {
        send(command: unknown) {
            if (!(command instanceof GetSecretValueCommand)) {
                throw new Error('unexpected command')
            }
            const { SecretId, VersionStage } = command.input
            const entry = versions[SecretId as string]
            const payload = VersionStage === 'AWSPREVIOUS' ? entry?.previous : entry?.current
            if (payload === undefined) {
                throw new ResourceNotFoundException({ message: 'not found', $metadata: {} })
            }
            return Promise.resolve({
                SecretString: JSON.stringify(payload),
                VersionId: VersionStage === 'AWSPREVIOUS' ? 'v-old' : 'v-new',
                CreatedDate: createdAt,
            })
        },
    }
}

const store = (versions: Versions) =>
    createSecretsManagerStore({ client: fakeClient(versions), prefix: 'integrations/' })

describe('secrets manager store', () => {
    it('reports steady and serves no previous when the secret has never been rotated', async () => {
        const snapshot = await store({
            'integrations/hubspot': { current: { HUBSPOT_APP_CLIENT_ID: 'id', HUBSPOT_APP_CLIENT_SECRET: 'sec' } },
        }).loadProvider('hubspot')

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({ state: 'steady', value: 'sec' })
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).not.toHaveProperty('previous')
    })

    it('reports steady when a previous version exists but holds the same value', async () => {
        const snapshot = await store({
            'integrations/hubspot': {
                current: { HUBSPOT_APP_CLIENT_SECRET: 'same' },
                previous: { HUBSPOT_APP_CLIENT_SECRET: 'same' },
            },
        }).loadProvider('hubspot')

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('steady')
    })

    it('reports rotating with both values when the versions differ', async () => {
        const snapshot = await store({
            'integrations/hubspot': {
                current: { HUBSPOT_APP_CLIENT_SECRET: 'new' },
                previous: { HUBSPOT_APP_CLIENT_SECRET: 'old' },
            },
        }).loadProvider('hubspot')

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']).toMatchObject({
            state: 'rotating',
            value: 'new',
            previous: 'old',
        })
    })

    // The per-field diff is the reason for one AWS secret per provider: rotating one
    // credential must not make every other field of the same app look mid-rotation.
    it('only marks the field that actually changed as rotating', async () => {
        const snapshot = await store({
            'integrations/hubspot': {
                current: { HUBSPOT_APP_CLIENT_ID: 'id', HUBSPOT_APP_CLIENT_SECRET: 'new' },
                previous: { HUBSPOT_APP_CLIENT_ID: 'id', HUBSPOT_APP_CLIENT_SECRET: 'old' },
            },
        }).loadProvider('hubspot')

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_ID']?.state).toBe('steady')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('rotating')
    })

    it('serves no value at all for a field marked in recovery', async () => {
        const snapshot = await store({
            'integrations/hubspot': {
                current: {
                    HUBSPOT_APP_CLIENT_SECRET: 'burned',
                    _state: { HUBSPOT_APP_CLIENT_SECRET: 'recovery' },
                },
            },
        }).loadProvider('hubspot')

        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.state).toBe('recovery')
        expect(snapshot?.secrets['HUBSPOT_APP_CLIENT_SECRET']?.value).toBeUndefined()
    })

    // Adding a credential has to be a reviewed code change, not just a secrets edit —
    // otherwise the provider manifest stops being a statement of what we hold.
    it('ignores fields that are present in the secret but absent from the manifest', async () => {
        const snapshot = await store({
            'integrations/hubspot': {
                current: { HUBSPOT_APP_CLIENT_SECRET: 'sec', SOMETHING_UNDECLARED: 'leak-me' },
            },
        }).loadProvider('hubspot')

        expect(Object.keys(snapshot?.secrets ?? {})).toEqual(['HUBSPOT_APP_CLIENT_SECRET'])
    })

    it('never exposes the reserved _state marker as a credential', async () => {
        const snapshot = await store({
            'integrations/hubspot': {
                current: { HUBSPOT_APP_CLIENT_SECRET: 'sec', _state: { HUBSPOT_APP_CLIENT_ID: 'recovery' } },
            },
        }).loadProvider('hubspot')

        expect(snapshot?.secrets).not.toHaveProperty('_state')
    })

    it('returns null for a provider with no secret in this environment', async () => {
        expect(await store({}).loadProvider('hubspot')).toBeNull()
    })

    it('returns null for a provider outside the manifest', async () => {
        expect(await store({}).loadProvider('not-a-provider')).toBeNull()
    })
})
