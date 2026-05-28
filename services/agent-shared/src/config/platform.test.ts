import { z } from 'zod'

import { extendEnvKeyMap, loadConfigFromEnv, PLATFORM_ENV_KEY_MAP, PlatformConfigSchema } from './platform'

describe('PlatformConfigSchema', () => {
    it('exposes defaults for all platform fields', () => {
        const cfg = PlatformConfigSchema.parse({})
        expect(cfg.posthogDbUrl).toContain('postgres://')
        expect(cfg.agentDbUrl).toContain('postgres://')
        expect(cfg.bundleRoot.length).toBeGreaterThan(0)
        expect(cfg.encryptionSaltKeys).toBe('')
        expect(cfg.logLevel).toBe('info')
        expect(cfg.redisUrl).toBeUndefined()
    })

    it('every shared field carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(PlatformConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})

describe('extendEnvKeyMap', () => {
    it('merges child keys on top of the platform map', () => {
        const merged = extendEnvKeyMap<{ port: number }>(PLATFORM_ENV_KEY_MAP, { PORT: 'port' })
        expect(merged.PORT).toBe('port')
        expect(merged.POSTHOG_DB_URL).toBe('posthogDbUrl')
    })
})

describe('loadConfigFromEnv', () => {
    const SubSchema = PlatformConfigSchema.extend({
        port: z.coerce.number().int().positive().default(3000).describe('test port'),
    })
    const SUB_MAP = extendEnvKeyMap<z.infer<typeof SubSchema>>(PLATFORM_ENV_KEY_MAP, { PORT: 'port' })

    it('parses an empty env into all defaults', () => {
        const cfg = loadConfigFromEnv(SubSchema, SUB_MAP, {})
        expect(cfg.port).toBe(3000)
        expect(cfg.posthogDbUrl).toContain('postgres://')
    })

    it('reads child + platform vars from the same env', () => {
        const cfg = loadConfigFromEnv(SubSchema, SUB_MAP, {
            PORT: '4040',
            REDIS_URL: 'redis://r:6379',
        })
        expect(cfg.port).toBe(4040)
        expect(cfg.redisUrl).toBe('redis://r:6379')
    })

    it('throws on malformed values (no NaN slipthrough)', () => {
        expect(() => loadConfigFromEnv(SubSchema, SUB_MAP, { PORT: 'banana' })).toThrow()
    })

    it('ignores env keys not in the map', () => {
        const cfg = loadConfigFromEnv(SubSchema, SUB_MAP, { COMPLETELY_UNRELATED: 'whatever' })
        expect(cfg.port).toBe(3000)
    })
})
