import { AgentIngressConfigSchema, loadAgentIngressConfig } from './config'

describe('loadAgentIngressConfig', () => {
    it('returns defaults for an empty env', () => {
        const cfg = loadAgentIngressConfig({})
        expect(cfg.port).toBe(8080)
        expect(cfg.routingMode).toBe('path')
        expect(cfg.pathPrefix).toBe('/agents')
        expect(cfg.internalSigningKey).toBeUndefined()
        expect(cfg.publicUrl).toBeUndefined()
        expect(cfg.logLevel).toBe('info')
    })

    it('publicUrl comes from AGENT_INGRESS_PUBLIC_URL', () => {
        const cfg = loadAgentIngressConfig({ AGENT_INGRESS_PUBLIC_URL: 'https://x.trycloudflare.com' })
        expect(cfg.publicUrl).toBe('https://x.trycloudflare.com')
    })

    it('coerces numeric env strings', () => {
        const cfg = loadAgentIngressConfig({ PORT: '3030' })
        expect(cfg.port).toBe(3030)
    })

    it('throws on bad numeric values', () => {
        expect(() => loadAgentIngressConfig({ PORT: 'not-a-port' })).toThrow()
    })

    it('throws on unknown routingMode rather than casting silently', () => {
        expect(() => loadAgentIngressConfig({ ROUTING_MODE: 'lol' })).toThrow()
    })

    it('internalSigningKey comes from AGENT_INTERNAL_SIGNING_KEY', () => {
        const cfg = loadAgentIngressConfig({ AGENT_INTERNAL_SIGNING_KEY: 'shared-key' })
        expect(cfg.internalSigningKey).toBe('shared-key')
    })

    it('platform fields (POSTHOG_DB_URL, AGENT_DB_URL, REDIS_URL) come from the shared schema', () => {
        const cfg = loadAgentIngressConfig({
            POSTHOG_DB_URL: 'postgres://x/y',
            AGENT_DB_URL: 'postgres://x/z',
            // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
            REDIS_URL: 'redis://localhost:6379',
        })
        expect(cfg.posthogDbUrl).toBe('postgres://x/y')
        expect(cfg.agentDbUrl).toBe('postgres://x/z')
        // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
        expect(cfg.redisUrl).toBe('redis://localhost:6379')
    })

    it('every schema key carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(AgentIngressConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})
