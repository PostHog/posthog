import { AgentRunnerConfigSchema, defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'

describe('loadAgentRunnerConfig', () => {
    afterEach(() => {
        vi.unstubAllEnvs()
    })

    it('returns prod-safe defaults when NODE_ENV=production', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.maxConcurrency).toBe(8)
        expect(cfg.useAiGateway).toBe(false)
        expect(cfg.aiGatewayUrl).toBe('http://ai-gateway/v1')
        expect(cfg.encryptionSaltKeys).toBe('')
        expect(cfg.logLevel).toBe('info')
        // S3 fields fall back to undefined in prod — fail-fast at boot lives in index.ts.
        expect(cfg.bundleS3Bucket).toBeUndefined()
        expect(cfg.memoryS3Bucket).toBeUndefined()
    })

    it('exposes dev SeaweedFS defaults when NODE_ENV is not production', () => {
        // vitest runs NODE_ENV=test — same branch as local dev.
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.bundleS3Bucket).toBe('posthog')
        expect(cfg.bundleS3Endpoint).toBe('http://localhost:8333')
        expect(cfg.memoryS3Bucket).toBe('posthog')
    })

    it('defaults sandboxBackend to docker in dev so bin/start works without configuration', () => {
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.sandboxBackend).toBe('docker')
    })

    it('leaves sandboxBackend unset in prod so selectSandboxPool fails fast at boot', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.sandboxBackend).toBeUndefined()
    })

    it('explicit SANDBOX_BACKEND wins over the dev default', () => {
        const cfg = loadAgentRunnerConfig({ SANDBOX_BACKEND: 'modal' })
        expect(cfg.sandboxBackend).toBe('modal')
    })

    it('defaults sandboxHostImage to the locally-built dev tag in dev so bin/start works without configuration', () => {
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.sandboxHostImage).toBe('posthog/agent-sandbox-host:dev')
    })

    it('leaves sandboxHostImage unset in prod so SANDBOX_HOST_IMAGE must be set explicitly', () => {
        vi.stubEnv('NODE_ENV', 'production')
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.sandboxHostImage).toBeUndefined()
    })

    it('explicit SANDBOX_HOST_IMAGE wins over the dev default', () => {
        const cfg = loadAgentRunnerConfig({ SANDBOX_HOST_IMAGE: 'ghcr.io/posthog/posthog-agent-sandbox-host:master' })
        expect(cfg.sandboxHostImage).toBe('ghcr.io/posthog/posthog-agent-sandbox-host:master')
    })

    it('AGENT_USE_AI_GATEWAY=1 parses to true', () => {
        const cfg = loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: '1' })
        expect(cfg.useAiGateway).toBe(true)
    })

    it('AGENT_USE_AI_GATEWAY=0 parses to false (legacy default)', () => {
        const cfg = loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: '0' })
        expect(cfg.useAiGateway).toBe(false)
    })

    it("'true' and 'false' string forms work too", () => {
        expect(loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: 'true' }).useAiGateway).toBe(true)
        expect(loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: 'false' }).useAiGateway).toBe(false)
    })

    it("rejects garbage AGENT_USE_AI_GATEWAY (won't silently default to false)", () => {
        // Previously `'lol' === '1'` was false so this silently became false.
        // Schema now rejects so we don't pretend.
        expect(() => loadAgentRunnerConfig({ AGENT_USE_AI_GATEWAY: 'lol' })).toThrow()
    })

    it('throws on bad numeric AGENT_MAX_CONCURRENCY', () => {
        expect(() => loadAgentRunnerConfig({ AGENT_MAX_CONCURRENCY: 'lots' })).toThrow()
    })

    it('every schema key carries a description (for runbook generation)', () => {
        for (const [key, field] of Object.entries(AgentRunnerConfigSchema.shape)) {
            expect((field as { description?: string }).description, `missing .describe() for ${key}`).toBeTruthy()
        }
    })
})

describe('defaultApiKeyFromConfig', () => {
    it('picks POSTHOG_AI_GATEWAY_KEY first', () => {
        const cfg = loadAgentRunnerConfig({
            POSTHOG_AI_GATEWAY_KEY: 'phx_gateway',
            ANTHROPIC_API_KEY: 'sk-ant',
            OPENAI_API_KEY: 'sk-openai',
            MODEL_API_KEY: 'sk-catchall',
        })
        expect(defaultApiKeyFromConfig(cfg)).toBe('phx_gateway')
    })

    it('falls back through Anthropic → OpenAI → catch-all', () => {
        expect(
            defaultApiKeyFromConfig(
                loadAgentRunnerConfig({
                    ANTHROPIC_API_KEY: 'sk-ant',
                    MODEL_API_KEY: 'sk-catchall',
                })
            )
        ).toBe('sk-ant')
        expect(
            defaultApiKeyFromConfig(
                loadAgentRunnerConfig({
                    OPENAI_API_KEY: 'sk-openai',
                    MODEL_API_KEY: 'sk-catchall',
                })
            )
        ).toBe('sk-openai')
        expect(defaultApiKeyFromConfig(loadAgentRunnerConfig({ MODEL_API_KEY: 'sk-catchall' }))).toBe('sk-catchall')
    })

    it('returns undefined when no key is set', () => {
        expect(defaultApiKeyFromConfig(loadAgentRunnerConfig({}))).toBeUndefined()
    })
})
