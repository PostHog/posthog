import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { isProductionEnv } from '@/db/role-guard'
import { loadConfig, loadMigrateConfig } from '@/lib/config'

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

describe('loadConfig database', () => {
    const DB_VARS = [
        'CREDENTIALS_SERVICE_ENV',
        'CREDENTIALS_SERVICE_DATABASE_URL',
        'CREDENTIALS_SERVICE_DATABASE_POOL_SIZE',
        'CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL',
    ]
    const URL = 'postgres://credentials:not-a-real-password@localhost:5432/credentials'

    beforeEach(() => {
        process.env.CREDENTIALS_SERVICE_ENV = 'local'
    })

    afterEach(() => {
        for (const key of DB_VARS) {
            delete process.env[key]
        }
    })

    // No URL must mean no database at all, so the service deploys before its database exists.
    it.each([
        ['no URL leaves the database off', {}, undefined],
        ['an empty URL leaves the database off', { CREDENTIALS_SERVICE_DATABASE_URL: '' }, undefined],
        ['a pool size with no URL is ignored', { CREDENTIALS_SERVICE_DATABASE_POOL_SIZE: '5' }, undefined],
        ['a URL defaults the pool to 20', { CREDENTIALS_SERVICE_DATABASE_URL: URL }, { url: URL, poolSize: 20 }],
        [
            'a URL takes the configured pool size',
            { CREDENTIALS_SERVICE_DATABASE_URL: URL, CREDENTIALS_SERVICE_DATABASE_POOL_SIZE: '7' },
            { url: URL, poolSize: 7 },
        ],
    ])('%s', (_label, env: Record<string, string>, expected) => {
        Object.assign(process.env, env)
        expect(loadConfig().database).toEqual(expected)
    })

    it.each([
        [
            'the user of the migrate URL',
            'postgres://migrator:not-a-real-password@localhost:5432/credentials',
            'migrator',
        ],
        ['no user when the migrate URL has none', 'postgres://localhost:5432/credentials', undefined],
    ])('reads %s', (_label, migrateUrl, expected) => {
        process.env.CREDENTIALS_SERVICE_DATABASE_URL = URL
        process.env.CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL = migrateUrl
        expect(loadConfig().database?.migrateUser).toBe(expected)
    })

    it('refuses to boot with a migrate URL that is not a URL', () => {
        process.env.CREDENTIALS_SERVICE_DATABASE_URL = URL
        process.env.CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL = 'not a url'
        expect(() => loadConfig()).toThrow('CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL')
    })

    it.each(['0', '-1', '20x'])('refuses to boot with pool size %j', (size) => {
        process.env.CREDENTIALS_SERVICE_DATABASE_URL = URL
        process.env.CREDENTIALS_SERVICE_DATABASE_POOL_SIZE = size
        expect(() => loadConfig()).toThrow('CREDENTIALS_SERVICE_DATABASE_POOL_SIZE')
    })
})

describe('loadConfig audit export requirement', () => {
    const KEYS = [
        'CREDENTIALS_SERVICE_ENV',
        'CREDENTIALS_SERVICE_DATABASE_URL',
        'CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_API_KEY',
    ]

    afterEach(() => {
        for (const key of KEYS) {
            delete process.env[key]
        }
    })

    it.each(['dev', 'prod-us', 'prod-eu'])('requires audit export in %s when a database is configured', (env) => {
        process.env.CREDENTIALS_SERVICE_ENV = env
        process.env.CREDENTIALS_SERVICE_DATABASE_URL = 'postgres://example'
        expect(() => loadConfig()).toThrow('audit export must be on wherever the integrations database is on')
    })

    it.each(['dev', 'prod-us', 'prod-eu'])('starts in %s with a database and audit export on', (env) => {
        Object.assign(process.env, {
            CREDENTIALS_SERVICE_ENV: env,
            CREDENTIALS_SERVICE_DATABASE_URL: 'postgres://example',
            CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED: 'true',
            CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST: 'https://capture.posthog.invalid',
            CREDENTIALS_SERVICE_AUDIT_CAPTURE_API_KEY: 'phc_fake',
        })
        expect(loadConfig().auditExport).toBeDefined()
    })

    it('starts in prod-us without a database or audit export', () => {
        process.env.CREDENTIALS_SERVICE_ENV = 'prod-us'
        expect(loadConfig().database).toBeUndefined()
    })

    it('starts in local with a database and audit export off', () => {
        process.env.CREDENTIALS_SERVICE_ENV = 'local'
        process.env.CREDENTIALS_SERVICE_DATABASE_URL = 'postgres://example'
        expect(loadConfig().auditExport).toBeUndefined()
    })
})

describe('loadConfig audit', () => {
    const KEYS = [
        'CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_API_KEY',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_VIA_PROXY',
        'HTTPS_PROXY',
    ]

    afterEach(() => {
        for (const key of KEYS) {
            delete process.env[key]
        }
    })

    it('leaves the export off when nothing is set', () => {
        expect(loadConfig().auditExport).toBeUndefined()
    })

    it('turns the export on with a host and a key', () => {
        process.env.CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED = 'true'
        process.env.CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST = 'https://capture.posthog.invalid'
        process.env.CREDENTIALS_SERVICE_AUDIT_CAPTURE_API_KEY = 'phc_fake'
        expect(loadConfig().auditExport).toMatchObject({ host: 'https://capture.posthog.invalid', batchSize: 500 })
    })

    it.each([
        ['no host or key', { CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED: 'true' }],
        [
            'a host that is not http',
            {
                CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED: 'true',
                CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST: 'ftp://x',
                CREDENTIALS_SERVICE_AUDIT_CAPTURE_API_KEY: 'phc_fake',
            },
        ],
    ])('fails the boot on %s', (_label, env) => {
        Object.assign(process.env, env)
        expect(() => loadConfig()).toThrow()
    })
})

describe('loadConfig audit capture proxy', () => {
    const KEYS = [
        'CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_API_KEY',
        'CREDENTIALS_SERVICE_AUDIT_CAPTURE_VIA_PROXY',
        'HTTPS_PROXY',
    ]
    const BASE = {
        CREDENTIALS_SERVICE_AUDIT_EXPORT_ENABLED: 'true',
        CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST: 'https://capture.posthog.invalid',
        CREDENTIALS_SERVICE_AUDIT_CAPTURE_API_KEY: 'phc_fake',
    }

    afterEach(() => {
        for (const key of KEYS) {
            delete process.env[key]
        }
    })

    it.each([
        [
            'true with HTTPS_PROXY',
            { VIA: 'true', PROXY: 'http://proxy.example.com:3128' },
            'http://proxy.example.com:3128',
        ],
        ['unset with HTTPS_PROXY', { PROXY: 'http://proxy.example.com:3128' }, undefined],
        ['false with HTTPS_PROXY', { VIA: 'false', PROXY: 'http://proxy.example.com:3128' }, undefined],
        ['unset without HTTPS_PROXY', {}, undefined],
    ])('sets proxyUrl for VIA_PROXY %s', (_label, { VIA, PROXY }: { VIA?: string; PROXY?: string }, expected) => {
        Object.assign(process.env, BASE)
        if (VIA) {
            process.env.CREDENTIALS_SERVICE_AUDIT_CAPTURE_VIA_PROXY = VIA
        }
        if (PROXY) {
            process.env.HTTPS_PROXY = PROXY
        }
        expect(loadConfig().auditExport?.proxyUrl).toBe(expected)
    })

    it.each([
        ['HTTPS_PROXY is missing', {}],
        ['HTTPS_PROXY is not an http URL', { HTTPS_PROXY: 'not a url' }],
        [
            'the capture host is not https',
            {
                HTTPS_PROXY: 'http://proxy.example.com:3128',
                CREDENTIALS_SERVICE_AUDIT_CAPTURE_HOST: 'http://capture.local',
            },
        ],
    ])('fails the boot with VIA_PROXY=true when %s', (_label, extra) => {
        Object.assign(process.env, BASE, { CREDENTIALS_SERVICE_AUDIT_CAPTURE_VIA_PROXY: 'true' }, extra)
        expect(() => loadConfig()).toThrow()
    })
})

describe('loadMigrateConfig', () => {
    const VARS = [
        'CREDENTIALS_SERVICE_DATABASE_URL',
        'CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL',
        'CREDENTIALS_SERVICE_RUNTIME_ROLE',
        'CREDENTIALS_SERVICE_PARTMAN_OPTIONAL',
    ]

    afterEach(() => {
        for (const key of VARS) {
            delete process.env[key]
        }
    })

    it.each([
        ['nothing set', {}, undefined],
        [
            'only the runtime URL',
            { CREDENTIALS_SERVICE_DATABASE_URL: 'postgres://runtime' },
            { url: 'postgres://runtime', runtimeRole: '', partmanOptional: false },
        ],
        [
            'the migrate URL wins over the runtime URL',
            {
                CREDENTIALS_SERVICE_DATABASE_URL: 'postgres://runtime',
                CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL: 'postgres://migrate',
                CREDENTIALS_SERVICE_RUNTIME_ROLE: 'svc_runtime',
            },
            { url: 'postgres://migrate', runtimeRole: 'svc_runtime', partmanOptional: false },
        ],
        [
            'partman is optional only when explicitly set to true',
            {
                CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL: 'postgres://migrate',
                CREDENTIALS_SERVICE_PARTMAN_OPTIONAL: 'true',
            },
            { url: 'postgres://migrate', runtimeRole: '', partmanOptional: true },
        ],
        [
            'other partman values keep it required',
            {
                CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL: 'postgres://migrate',
                CREDENTIALS_SERVICE_PARTMAN_OPTIONAL: 'TRUE',
            },
            { url: 'postgres://migrate', runtimeRole: '', partmanOptional: false },
        ],
    ])('%s', (_label, env, expected) => {
        Object.assign(process.env, env)
        expect(loadMigrateConfig()).toEqual(expected)
    })

    it.each(['bad role', 'role;DROP', '1role'])('rejects the role name %j', (role) => {
        process.env.CREDENTIALS_SERVICE_MIGRATE_DATABASE_URL = 'postgres://migrate'
        process.env.CREDENTIALS_SERVICE_RUNTIME_ROLE = role
        expect(() => loadMigrateConfig()).toThrow('CREDENTIALS_SERVICE_RUNTIME_ROLE')
    })
})

describe('isProductionEnv', () => {
    it.each([
        ['prod-us', true],
        ['prod-eu', true],
        ['production', true],
        ['Prod-us', true],
        ['prod_us', true],
        ['prod-us ', true],
        ['dev', false],
        ['test', false],
        ['staging', false],
    ])('%s is production: %s', (env, expected) => {
        expect(isProductionEnv(env)).toBe(expected)
    })
})
