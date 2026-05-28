/**
 * Typed configuration loader for the runner.
 *
 * Extends `PlatformConfigSchema` with the worker-loop knobs (concurrency,
 * model selection, per-provider API keys). Read once at boot in `index.ts`;
 * everything else inside the service receives the typed `Config`.
 *
 * Plan + rationale: `docs/agent-platform/plans/typed-config-loader.md`.
 */

import { z } from 'zod'

import { extendEnvKeyMap, loadConfigFromEnv, PLATFORM_ENV_KEY_MAP, PlatformConfigSchema } from '@posthog/agent-shared'

export const AgentRunnerConfigSchema = PlatformConfigSchema.extend({
    maxConcurrency: z.coerce.number().int().positive().default(8).describe('In-flight sessions per worker process.'),
    useLlmGateway: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('0')
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'When truthy (`1`/`true`), routes every model call through PostHog llm-gateway via posthogLlmGatewayModel(). Spec.model still picks the underlying model id.'
        ),
    llmGatewayUrl: z
        .string()
        .url()
        .default('http://llm-gateway/v1')
        .describe('Custom baseUrl for the posthogLlmGatewayModel factory. In prod points at the in-cluster service.'),
    posthogLlmGatewayKey: z
        .string()
        .optional()
        .describe('PostHog gateway PAT (`phx_...`). First non-empty wins for pi-ai default apiKey.'),
    anthropicApiKey: z.string().optional().describe('Anthropic API key. Second-priority for pi-ai default apiKey.'),
    openaiApiKey: z.string().optional().describe('OpenAI API key. Third-priority for pi-ai default apiKey.'),
    modelApiKey: z.string().optional().describe('Catch-all model API key. Last-priority for pi-ai default apiKey.'),
    posthogAnalyticsApiKey: z
        .string()
        .optional()
        .describe(
            'PostHog project API key for the LLM analytics sink. Captures `$ai_generation` + `$ai_span` via standard /capture. Unset → NoopAnalyticsSink (dev / harness).'
        ),
    posthogAnalyticsHost: z
        .string()
        .url()
        .optional()
        .describe('PostHog capture host for the analytics sink. Defaults to `https://us.posthog.com` when unset.'),
})

export type AgentRunnerConfig = z.infer<typeof AgentRunnerConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentRunnerConfig>(PLATFORM_ENV_KEY_MAP, {
    AGENT_MAX_CONCURRENCY: 'maxConcurrency',
    AGENT_USE_LLM_GATEWAY: 'useLlmGateway',
    POSTHOG_LLM_GATEWAY_URL: 'llmGatewayUrl',
    POSTHOG_LLM_GATEWAY_KEY: 'posthogLlmGatewayKey',
    ANTHROPIC_API_KEY: 'anthropicApiKey',
    OPENAI_API_KEY: 'openaiApiKey',
    MODEL_API_KEY: 'modelApiKey',
    POSTHOG_ANALYTICS_API_KEY: 'posthogAnalyticsApiKey',
    POSTHOG_ANALYTICS_HOST: 'posthogAnalyticsHost',
})

export function loadAgentRunnerConfig(env: NodeJS.ProcessEnv = process.env): AgentRunnerConfig {
    return loadConfigFromEnv(AgentRunnerConfigSchema, ENV_KEY_MAP, env)
}

/**
 * Returns the first non-empty provider key in the same order the legacy
 * runner used to: gateway → anthropic → openai → catch-all. Centralized
 * here so the runner doesn't sprinkle the priority order across files.
 */
export function defaultApiKeyFromConfig(cfg: AgentRunnerConfig): string | undefined {
    return cfg.posthogLlmGatewayKey ?? cfg.anthropicApiKey ?? cfg.openaiApiKey ?? cfg.modelApiKey
}
