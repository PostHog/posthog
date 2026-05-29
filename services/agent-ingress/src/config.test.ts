import { AgentIngressConfigSchema, loadAgentIngressConfig } from './config'

describe('loadAgentIngressConfig', () => {
    it('returns defaults for an empty env', () => {
        const cfg = loadAgentIngressConfig({})
        expect(cfg.port).toBe(8080)
        expect(cfg.teamId).toBe(1)
        expect(cfg.routingMode).toBe('path')
        expect(cfg.pathPrefix).toBe('/agents')
        expect(cfg.previewSecret).toBeUndefined()
        expect(cfg.logLevel).toBe('info')
    })

    it('coerces numeric env strings', () => {
        const cfg = loadAgentIngressConfig({ PORT: '3030', TEAM_ID: '42' })
        expect(cfg.port).toBe(3030)
        expect(cfg.teamId).toBe(42)
    })

    it('throws on bad numeric values', () => {
        expect(() => loadAgentIngressConfig({ PORT: 'not-a-port' })).toThrow()
    })

    it('throws on unknown routingMode rather than casting silently', () => {
        expect(() => loadAgentIngressConfig({ ROUTING_MODE: 'lol' })).toThrow()
    })

    it('previewSecret comes from AGENT_PREVIEW_SECRET (single source of truth)', () => {
        const cfg = loadAgentIngressConfig({ AGENT_PREVIEW_SECRET: 'dedicated-preview-secret' })
        expect(cfg.previewSecret).toBe('dedicated-preview-secret')
    })

    it('previewSecret does NOT fall back to INTERNAL_SECRET — silent mismatch on the Django side would 401', () => {
        // Regression: there used to be an INTERNAL_SECRET fallback here
        // that wasn't mirrored on the Django side, so a dev env with
        // only INTERNAL_SECRET set would have ingress requiring tokens
        // while Django sent none → opaque 401s on every draft invoke.
        const cfg = loadAgentIngressConfig({ INTERNAL_SECRET: 'shared-with-janitor' })
        expect(cfg.previewSecret).toBeUndefined()
    })

    it('platform fields (POSTHOG_DB_URL, AGENT_DB_URL, REDIS_URL) come from the shared schema', () => {
        const cfg = loadAgentIngressConfig({
            POSTHOG_DB_URL: 'postgres://x/y',
            AGENT_DB_URL: 'postgres://x/z',
            REDIS_URL: 'redis://localhost:6379',
        })
        expect(cfg.posthogDbUrl).toBe('postgres://x/y')
        expect(cfg.agentDbUrl).toBe('postgres://x/z')
        expect(cfg.redisUrl).toBe('redis://localhost:6379')
    })

    it('every schema key carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(AgentIngressConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})
