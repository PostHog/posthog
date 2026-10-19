import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import { loadConfig } from '@/lib/config'

const VAR = 'CREDENTIALS_SERVICE_RELOAD_SECONDS'

describe('loadConfig integers', () => {
    afterEach(() => {
        delete process.env[VAR]
    })

    it.each([
        ['unset falls back to the default', undefined, 30],
        ['a valid value parses', '45', 45],
    ])('%s', (_label, value, expected) => {
        if (value !== undefined) {
            process.env[VAR] = value
        }
        expect(loadConfig().reloadSeconds).toBe(expected)
    })

    // Boot is fail-fast everywhere else; a malformed number must not silently run a
    // cadence the operator did not set.
    it('throws on a malformed value instead of silently defaulting', () => {
        process.env[VAR] = 'not-a-number'
        expect(() => loadConfig()).toThrow(VAR)
    })
})

describe('loadConfig production guards', () => {
    const PROD_VARS = ['NODE_ENV', 'CREDENTIALS_SERVICE_ENV']

    afterEach(() => {
        for (const key of PROD_VARS) {
            delete process.env[key]
        }
    })

    it('refuses to boot in production without CREDENTIALS_SERVICE_ENV', () => {
        process.env.NODE_ENV = 'production'
        expect(() => loadConfig()).toThrow('CREDENTIALS_SERVICE_ENV')
    })

    it('boots in production once every required variable is set', () => {
        process.env.NODE_ENV = 'production'
        process.env.CREDENTIALS_SERVICE_ENV = 'prod-us'
        expect(loadConfig().env).toBe('prod-us')
    })
})

describe('loadConfig secret source', () => {
    const SOURCE_VARS = [
        'CREDENTIALS_SERVICE_SECRET_SOURCE',
        'CREDENTIALS_SERVICE_SECRET_NAME',
        'CREDENTIALS_SERVICE_SECRET_NAMESPACE',
        'KUBERNETES_SERVICE_HOST',
        'KUBERNETES_SERVICE_PORT',
    ]
    const dirs: string[] = []

    afterEach(async () => {
        for (const key of SOURCE_VARS) {
            delete process.env[key]
        }
        await Promise.all(dirs.splice(0).map((d) => rm(d, { recursive: true, force: true })))
    })

    async function serviceAccountDir(namespace: string | null): Promise<string> {
        const dir = await mkdtemp(join(tmpdir(), 'credentials-sa-'))
        dirs.push(dir)
        if (namespace !== null) {
            await writeFile(join(dir, 'namespace'), `${namespace}\n`)
        }
        return dir
    }

    it.each([
        ['unset reads the mount directory', {}, undefined],
        ['directory reads the mount directory', { CREDENTIALS_SERVICE_SECRET_SOURCE: 'directory' }, undefined],
        [
            'kubernetes reads the service account namespace and the default secret name',
            { CREDENTIALS_SERVICE_SECRET_SOURCE: 'kubernetes' },
            { apiUrl: 'https://10.0.0.1:443', namespace: 'from-file', secretName: 'credentials-service-secrets' },
        ],
        [
            'kubernetes prefers an explicit namespace and secret name',
            {
                CREDENTIALS_SERVICE_SECRET_SOURCE: 'kubernetes',
                CREDENTIALS_SERVICE_SECRET_NAMESPACE: 'explicit',
                CREDENTIALS_SERVICE_SECRET_NAME: 'other-secret',
            },
            { namespace: 'explicit', secretName: 'other-secret' },
        ],
        [
            'kubernetes brackets an IPv6 service host',
            { CREDENTIALS_SERVICE_SECRET_SOURCE: 'kubernetes', KUBERNETES_SERVICE_HOST: 'fd00::1' },
            { apiUrl: 'https://[fd00::1]:443' },
        ],
    ])('%s', async (_label, env: Record<string, string>, expected) => {
        process.env.KUBERNETES_SERVICE_HOST = '10.0.0.1'
        process.env.KUBERNETES_SERVICE_PORT = '443'
        Object.assign(process.env, env)
        const dir = await serviceAccountDir('from-file')

        const config = loadConfig(dir)

        if (expected === undefined) {
            expect(config.kubernetes).toBeUndefined()
        } else {
            expect(config.kubernetes).toMatchObject(expected)
            // The token rotates, so the source must know the file, not a value read at boot.
            expect(config.kubernetes).toMatchObject({ tokenFile: join(dir, 'token'), caFile: join(dir, 'ca.crt') })
        }
    })

    it.each([
        ['an unknown source', { CREDENTIALS_SERVICE_SECRET_SOURCE: 'kube' }, 'CREDENTIALS_SERVICE_SECRET_SOURCE', true],
        [
            'kubernetes outside a cluster',
            { CREDENTIALS_SERVICE_SECRET_SOURCE: 'kubernetes', KUBERNETES_SERVICE_HOST: '' },
            'KUBERNETES_SERVICE_HOST',
            true,
        ],
        [
            'kubernetes with no namespace anywhere',
            { CREDENTIALS_SERVICE_SECRET_SOURCE: 'kubernetes' },
            'CREDENTIALS_SERVICE_SECRET_NAMESPACE',
            false,
        ],
        [
            'a secret name the API path cannot carry',
            { CREDENTIALS_SERVICE_SECRET_SOURCE: 'kubernetes', CREDENTIALS_SERVICE_SECRET_NAME: '../configmaps/x' },
            'CREDENTIALS_SERVICE_SECRET_NAME',
            true,
        ],
    ])('refuses to boot with %s', async (_label, env: Record<string, string>, message, namespaceFile) => {
        process.env.KUBERNETES_SERVICE_HOST = '10.0.0.1'
        process.env.KUBERNETES_SERVICE_PORT = '443'
        Object.assign(process.env, env)
        const dir = await serviceAccountDir(namespaceFile ? 'posthog' : null)

        expect(() => loadConfig(dir)).toThrow(message)
    })
})
