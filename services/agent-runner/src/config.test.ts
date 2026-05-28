import { AgentRunnerConfigSchema, defaultApiKeyFromConfig, loadAgentRunnerConfig } from './config'

describe('loadAgentRunnerConfig', () => {
    it('returns defaults for an empty env', () => {
        const cfg = loadAgentRunnerConfig({})
        expect(cfg.maxConcurrency).toBe(8)
        expect(cfg.useLlmGateway).toBe(false)
        expect(cfg.llmGatewayUrl).toBe('http://llm-gateway/v1')
        expect(cfg.encryptionSaltKeys).toBe('')
        expect(cfg.logLevel).toBe('info')
    })

    it('AGENT_USE_LLM_GATEWAY=1 parses to true', () => {
        const cfg = loadAgentRunnerConfig({ AGENT_USE_LLM_GATEWAY: '1' })
        expect(cfg.useLlmGateway).toBe(true)
    })

    it('AGENT_USE_LLM_GATEWAY=0 parses to false (legacy default)', () => {
        const cfg = loadAgentRunnerConfig({ AGENT_USE_LLM_GATEWAY: '0' })
        expect(cfg.useLlmGateway).toBe(false)
    })

    it("'true' and 'false' string forms work too", () => {
        expect(loadAgentRunnerConfig({ AGENT_USE_LLM_GATEWAY: 'true' }).useLlmGateway).toBe(true)
        expect(loadAgentRunnerConfig({ AGENT_USE_LLM_GATEWAY: 'false' }).useLlmGateway).toBe(false)
    })

    it("rejects garbage AGENT_USE_LLM_GATEWAY (won't silently default to false)", () => {
        // Previously `'lol' === '1'` was false so this silently became false.
        // Schema now rejects so we don't pretend.
        expect(() => loadAgentRunnerConfig({ AGENT_USE_LLM_GATEWAY: 'lol' })).toThrow()
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
    it('picks POSTHOG_LLM_GATEWAY_KEY first', () => {
        const cfg = loadAgentRunnerConfig({
            POSTHOG_LLM_GATEWAY_KEY: 'phx_gateway',
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
