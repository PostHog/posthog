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

import {
    extendEnvKeyMap,
    isDev,
    loadConfigFromEnv,
    PLATFORM_ENV_KEY_MAP,
    PlatformConfigSchema,
} from '@posthog/agent-shared'

// Dev SeaweedFS defaults — the PostHog dev stack pre-creates the `posthog`
// bucket on `seaweedfs:8333`. Matches the same defaults session-replay v2
// uses (`SESSION_RECORDING_V2_S3_*`). SeaweedFS S3 runs in anonymous mode,
// so the access/secret keys are placeholders (`any`). Gated by `isDev()`
// so prod (NODE_ENV=production) still has to set AGENT_{MEMORY,BUNDLE}_S3_*
// explicitly; without them the bundle-store fail-fast in index.ts trips.
const DEV_S3_ENDPOINT = 'http://localhost:8333'
const DEV_S3_BUCKET = 'posthog'
const DEV_S3_ACCESS_KEY_ID = 'any'
const DEV_S3_SECRET_ACCESS_KEY = 'any'

export const AgentRunnerConfigSchema = PlatformConfigSchema.extend({
    maxConcurrency: z.coerce.number().int().positive().default(8).describe('In-flight sessions per worker process.'),
    useAiGateway: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('0')
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'When truthy (`1`/`true`), routes every model call through PostHog ai-gateway via posthogAiGatewayModel(). Spec.model still picks the underlying model id.'
        ),
    aiGatewayUrl: z
        .string()
        .url()
        .default('http://ai-gateway/v1')
        .describe('Custom baseUrl for the posthogAiGatewayModel factory. In prod points at the in-cluster service.'),
    posthogAiGatewayKey: z
        .string()
        .optional()
        .describe('PostHog ai-gateway PAT (`phx_...`). First non-empty wins for pi-ai default apiKey.'),
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
    memoryS3Endpoint: z
        .string()
        .url()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ENDPOINT : undefined))
        .describe(
            'S3-compatible endpoint for agent-memory file storage. Dev defaults to local SeaweedFS; prod unset disables memory tools.'
        ),
    memoryS3Region: z
        .string()
        .default('us-east-1')
        .describe('Region for the memory bucket. SeaweedFS ignores; real S3 honours.'),
    memoryS3Bucket: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_BUCKET : undefined))
        .describe('Bucket holding agent memory files. Dev defaults to the SeaweedFS `posthog` bucket.'),
    memoryS3Prefix: z
        .string()
        .default('agent_memory')
        .describe('Per-deployment key prefix inside the bucket. Default `agent_memory`.'),
    memoryS3AccessKeyId: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ACCESS_KEY_ID : undefined))
        .describe(
            'Optional explicit S3 access key id; falls back to SDK default chain. Dev defaults to SeaweedFS anonymous (`any`/`any`).'
        ),
    memoryS3SecretAccessKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_SECRET_ACCESS_KEY : undefined))
        .describe('Optional explicit S3 secret access key. Dev defaults to SeaweedFS anonymous (`any`/`any`).'),
    memoryS3ForcePathStyle: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('1')
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'forcePathStyle for the S3 client. Default true (SeaweedFS + MinIO both need it; real S3 accepts it).'
        ),
    bundleS3Endpoint: z
        .string()
        .url()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ENDPOINT : undefined))
        .describe(
            'S3-compatible endpoint for agent-bundle storage. Dev defaults to local SeaweedFS; prod unset means SDK regional default.'
        ),
    bundleS3Region: z
        .string()
        .default('us-east-1')
        .describe('Region for the bundle bucket. SeaweedFS ignores; real S3 honours.'),
    bundleS3Bucket: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_BUCKET : undefined))
        .describe(
            'Bucket holding agent bundles (per-revision compiled code + spec + skills). Dev defaults to the SeaweedFS `posthog` bucket; prod must set explicitly or the runner fails closed at boot.'
        ),
    bundleS3Prefix: z
        .string()
        .default('agent_bundles')
        .describe('Per-deployment key prefix inside the bucket. Default `agent_bundles`.'),
    bundleS3AccessKeyId: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_ACCESS_KEY_ID : undefined))
        .describe(
            'Optional explicit S3 access key id; falls back to SDK default chain. Dev defaults to SeaweedFS anonymous (`any`/`any`).'
        ),
    bundleS3SecretAccessKey: z
        .string()
        .optional()
        .transform((v): string | undefined => v ?? (isDev() ? DEV_S3_SECRET_ACCESS_KEY : undefined))
        .describe('Optional explicit S3 secret access key. Dev defaults to SeaweedFS anonymous (`any`/`any`).'),
    bundleS3ForcePathStyle: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('1')
        .transform((v) => v === '1' || v === 'true')
        .describe(
            'forcePathStyle for the S3 client. Default true (SeaweedFS + MinIO both need it; real S3 accepts it).'
        ),
})

export type AgentRunnerConfig = z.infer<typeof AgentRunnerConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentRunnerConfig>(PLATFORM_ENV_KEY_MAP, {
    AGENT_MAX_CONCURRENCY: 'maxConcurrency',
    AGENT_USE_AI_GATEWAY: 'useAiGateway',
    POSTHOG_AI_GATEWAY_URL: 'aiGatewayUrl',
    POSTHOG_AI_GATEWAY_KEY: 'posthogAiGatewayKey',
    ANTHROPIC_API_KEY: 'anthropicApiKey',
    OPENAI_API_KEY: 'openaiApiKey',
    MODEL_API_KEY: 'modelApiKey',
    POSTHOG_ANALYTICS_API_KEY: 'posthogAnalyticsApiKey',
    POSTHOG_ANALYTICS_HOST: 'posthogAnalyticsHost',
    AGENT_MEMORY_S3_ENDPOINT: 'memoryS3Endpoint',
    AGENT_MEMORY_S3_REGION: 'memoryS3Region',
    AGENT_MEMORY_S3_BUCKET: 'memoryS3Bucket',
    AGENT_MEMORY_S3_PREFIX: 'memoryS3Prefix',
    AGENT_MEMORY_S3_ACCESS_KEY_ID: 'memoryS3AccessKeyId',
    AGENT_MEMORY_S3_SECRET_ACCESS_KEY: 'memoryS3SecretAccessKey',
    AGENT_MEMORY_S3_FORCE_PATH_STYLE: 'memoryS3ForcePathStyle',
    AGENT_BUNDLE_S3_ENDPOINT: 'bundleS3Endpoint',
    AGENT_BUNDLE_S3_REGION: 'bundleS3Region',
    AGENT_BUNDLE_S3_BUCKET: 'bundleS3Bucket',
    AGENT_BUNDLE_S3_PREFIX: 'bundleS3Prefix',
    AGENT_BUNDLE_S3_ACCESS_KEY_ID: 'bundleS3AccessKeyId',
    AGENT_BUNDLE_S3_SECRET_ACCESS_KEY: 'bundleS3SecretAccessKey',
    AGENT_BUNDLE_S3_FORCE_PATH_STYLE: 'bundleS3ForcePathStyle',
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
    return cfg.posthogAiGatewayKey ?? cfg.anthropicApiKey ?? cfg.openaiApiKey ?? cfg.modelApiKey
}
