import { afterEach, describe, expect, it } from 'vitest'

import { createKms } from '@/crypto/kms'
import { LocalKms } from '@/crypto/local-kms'
import { loadConfig } from '@/lib/config'

const VARS = [
    'CREDENTIALS_SERVICE_ENV',
    'CREDENTIALS_SERVICE_KMS_PROVIDER',
    'CREDENTIALS_SERVICE_KMS_KEY_ID',
    'CREDENTIALS_SERVICE_KMS_REGION',
    'CREDENTIALS_SERVICE_KMS_ENDPOINT',
    'CREDENTIALS_SERVICE_KMS_PROXY_URL',
    'CREDENTIALS_SERVICE_KMS_LOCAL_KEYS',
]

const KEY_A = Buffer.alloc(32, 0xa1).toString('base64')
const KEY_B = Buffer.alloc(32, 0xb2).toString('base64')

function withEnv(env: Record<string, string>): void {
    for (const [key, value] of Object.entries(env)) {
        process.env[key] = value
    }
}

describe('loadConfig kms', () => {
    afterEach(() => {
        for (const key of VARS) {
            delete process.env[key]
        }
    })

    it('leaves the KMS unset when no provider is configured', () => {
        expect(loadConfig().kms).toBeUndefined()
    })

    it('reads an aws provider', () => {
        withEnv({
            CREDENTIALS_SERVICE_KMS_PROVIDER: 'aws',
            CREDENTIALS_SERVICE_KMS_KEY_ID: 'alias/integrations',
            CREDENTIALS_SERVICE_KMS_REGION: 'us-east-1',
            CREDENTIALS_SERVICE_KMS_PROXY_URL: 'http://proxy.example.com:3128',
        })

        expect(loadConfig().kms).toEqual({
            provider: 'aws',
            keyId: 'alias/integrations',
            region: 'us-east-1',
            proxyUrl: 'http://proxy.example.com:3128',
        })
    })

    it('reads local keys in order and builds a LocalKms that wraps with the first', async () => {
        withEnv({ CREDENTIALS_SERVICE_KMS_PROVIDER: 'local', CREDENTIALS_SERVICE_KMS_LOCAL_KEYS: `${KEY_A}, ${KEY_B}` })

        const config = loadConfig().kms
        expect(config).toEqual({
            provider: 'local',
            keys: [Buffer.from(KEY_A, 'base64'), Buffer.from(KEY_B, 'base64')],
        })
        const kms = createKms(config!)
        expect(kms).toBeInstanceOf(LocalKms)
        const dataKey = await kms.generateDataKey({ integrationId: 'i', ownerId: '1', kind: 'slack' })
        expect(dataKey.keyId).toBe(LocalKms.keyIdFor(Buffer.from(KEY_A, 'base64')))
    })

    it.each<[string, Record<string, string>, string]>([
        ['an unknown provider', { CREDENTIALS_SERVICE_KMS_PROVIDER: 'vault' }, 'CREDENTIALS_SERVICE_KMS_PROVIDER'],
        ['aws without a key id', { CREDENTIALS_SERVICE_KMS_PROVIDER: 'aws' }, 'CREDENTIALS_SERVICE_KMS_KEY_ID'],
        [
            'a proxy that is not an http URL',
            {
                CREDENTIALS_SERVICE_KMS_PROVIDER: 'aws',
                CREDENTIALS_SERVICE_KMS_KEY_ID: 'alias/integrations',
                CREDENTIALS_SERVICE_KMS_PROXY_URL: 'socks5://user:fake-password@proxy',
            },
            'CREDENTIALS_SERVICE_KMS_PROXY_URL must be an http(s) URL',
        ],
        ['local without keys', { CREDENTIALS_SERVICE_KMS_PROVIDER: 'local' }, 'CREDENTIALS_SERVICE_KMS_LOCAL_KEYS'],
        [
            'a local key of the wrong length',
            {
                CREDENTIALS_SERVICE_KMS_PROVIDER: 'local',
                CREDENTIALS_SERVICE_KMS_LOCAL_KEYS: `${KEY_A},${Buffer.alloc(16).toString('base64')}`,
            },
            'entry 1 is not a base64 32-byte key',
        ],
        [
            'a local key with characters outside base64',
            { CREDENTIALS_SERVICE_KMS_PROVIDER: 'local', CREDENTIALS_SERVICE_KMS_LOCAL_KEYS: `${KEY_A}!` },
            'entry 0 is not a base64 32-byte key',
        ],
        [
            'the local provider in prod-us',
            {
                CREDENTIALS_SERVICE_ENV: 'prod-us',
                CREDENTIALS_SERVICE_KMS_PROVIDER: 'local',
                CREDENTIALS_SERVICE_KMS_LOCAL_KEYS: KEY_A,
            },
            'not allowed in prod-us',
        ],
        [
            'the local provider in prod-eu',
            {
                CREDENTIALS_SERVICE_ENV: 'prod-eu',
                CREDENTIALS_SERVICE_KMS_PROVIDER: 'local',
                CREDENTIALS_SERVICE_KMS_LOCAL_KEYS: KEY_A,
            },
            'not allowed in prod-eu',
        ],
        [
            'the local provider in prod-staging',
            {
                CREDENTIALS_SERVICE_ENV: 'prod-staging',
                CREDENTIALS_SERVICE_KMS_PROVIDER: 'local',
                CREDENTIALS_SERVICE_KMS_LOCAL_KEYS: KEY_A,
            },
            'not allowed in prod-staging',
        ],
        [
            'the local provider in a production env with a typo in its case',
            {
                CREDENTIALS_SERVICE_ENV: 'PRODUCTION',
                CREDENTIALS_SERVICE_KMS_PROVIDER: 'local',
                CREDENTIALS_SERVICE_KMS_LOCAL_KEYS: KEY_A,
            },
            'not allowed in PRODUCTION',
        ],
    ])('refuses to boot with %s', (_label, env, message) => {
        withEnv(env)

        expect(() => loadConfig()).toThrow(message)
    })

    it('never puts a proxy password in the boot error', () => {
        withEnv({
            CREDENTIALS_SERVICE_KMS_PROVIDER: 'aws',
            CREDENTIALS_SERVICE_KMS_KEY_ID: 'alias/integrations',
            CREDENTIALS_SERVICE_KMS_PROXY_URL: 'socks5://user:fake-password@proxy',
        })

        expect(() => loadConfig()).toThrow(
            expect.objectContaining({ message: expect.not.stringContaining('fake-password') })
        )
    })
})
