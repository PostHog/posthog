import { AgentJanitorConfigSchema, loadAgentJanitorConfig } from './config'

describe('loadAgentJanitorConfig', () => {
    it('returns defaults for an empty env', () => {
        const cfg = loadAgentJanitorConfig({})
        expect(cfg.port).toBe(8082)
        expect(cfg.maxRetries).toBe(3)
        expect(cfg.logLevel).toBe('info')
        expect(cfg.internalSigningKey).toBeUndefined()
        expect(cfg.posthogDbUrl).toContain('postgres://')
    })

    it('coerces numeric env strings without leaking NaN', () => {
        const cfg = loadAgentJanitorConfig({
            PORT: '3031',
            STUCK_RUNNING_MS: '120000',
            MAX_RETRIES: '5',
        })
        expect(cfg.port).toBe(3031)
        expect(cfg.stuckRunningMs).toBe(120_000)
        expect(cfg.maxRetries).toBe(5)
    })

    it('throws a clear error on a bad numeric value rather than producing NaN', () => {
        expect(() => loadAgentJanitorConfig({ PORT: 'lol' })).toThrow()
    })

    it('throws on an unknown logLevel rather than casting silently', () => {
        expect(() => loadAgentJanitorConfig({ LOG_LEVEL: 'TRACE' })).toThrow()
    })

    it('respects ENV_KEY_MAP — unknown env keys are ignored, not surfaced as schema errors', () => {
        // Stray env vars shouldn't fail the loader; only mapped ones are read.
        const cfg = loadAgentJanitorConfig({
            PORT: '3031',
            RANDOM_UNMAPPED_VAR: 'whatever',
        })
        expect(cfg.port).toBe(3031)
    })

    it('every schema key carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(AgentJanitorConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})
