import { EncryptedFields, MemoryRevisionStore } from '@posthog/agent-shared-v2'

import { makeEncryptedEnvResolver } from './encrypted-env-resolver'

const KEY = '01234567890123456789012345678901'

function freshSession(overrides: Record<string, unknown> = {}): never {
    return {
        id: 's1',
        application_id: 'app1',
        revision_id: 'rev1',
        team_id: 1,
        external_key: null,
        state: 'queued',
        principal: null,
        conversation: [],
        pending_inputs: [],
        retry_count: 0,
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
        ...overrides,
    } as never
}

describe('makeEncryptedEnvResolver', () => {
    let revisions: MemoryRevisionStore
    let encryption: EncryptedFields

    beforeEach(() => {
        revisions = new MemoryRevisionStore()
        encryption = new EncryptedFields(KEY)
    })

    async function seedApp(encryptedEnv: string | null): Promise<string> {
        const app = await revisions.createApplication({
            team_id: 1,
            slug: 'a',
            name: 'A',
            description: '',
            encrypted_env: encryptedEnv,
        })
        return app.id
    }

    it('returns {} when no encrypted_env is set on the application', async () => {
        const appId = await seedApp(null)
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ application_id: appId }))).toEqual({})
    })

    it('returns {} when the application is unknown (revision_store returns null)', async () => {
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ application_id: 'nope' }))).toEqual({})
    })

    it('decrypts a JSON env block into a string-only map', async () => {
        const ct = encryption.encrypt(JSON.stringify({ STRIPE_KEY: 'sk_test_x', PORT: 8080 }))
        const appId = await seedApp(ct)
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ application_id: appId }))).toEqual({
            STRIPE_KEY: 'sk_test_x',
            PORT: '8080',
        })
    })

    it('returns {} (not throw) when decryption fails — keeps the session alive', async () => {
        const otherKey = new EncryptedFields('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')
        const ct = otherKey.encrypt(JSON.stringify({ X: 'y' }))
        const appId = await seedApp(ct)
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ application_id: appId }))).toEqual({})
    })
})
