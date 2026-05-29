/**
 * Typed configuration loader for the janitor.
 *
 * Extends `PlatformConfigSchema` from `@posthog/agent-shared/config/platform`
 * with the janitor-specific knobs (port, sweep thresholds, internal secret).
 * Every other `process.env.*` access in this package is blocked by the
 * `agent-janitor-no-process-env` semgrep rule — env reads go through
 * `loadAgentJanitorConfig()` only.
 *
 * Plan + rationale: `docs/agent-platform/plans/typed-config-loader.md`.
 */

import { z } from 'zod'

import { extendEnvKeyMap, loadConfigFromEnv, PLATFORM_ENV_KEY_MAP, PlatformConfigSchema } from '@posthog/agent-shared'

const ONE_MINUTE_MS = 60_000

export const AgentJanitorConfigSchema = PlatformConfigSchema.extend({
    port: z.coerce.number().int().positive().default(8082).describe('HTTP listen port.'),
    internalSecret: z
        .string()
        .optional()
        .describe(
            'Shared secret Django sends as `x-internal-secret`. Required in prod for any endpoint other than `/healthz`.'
        ),
    stuckRunningMs: z.coerce
        .number()
        .int()
        .positive()
        .default(5 * ONE_MINUTE_MS)
        .describe('Sweep re-queues `running` sessions older than this many ms.'),
    stuckWaitingMs: z.coerce
        .number()
        .int()
        .positive()
        .default(24 * 60 * ONE_MINUTE_MS)
        .describe('Sweep fails `waiting` sessions older than this many ms.'),
    idleCompletedMs: z.coerce
        .number()
        .int()
        .positive()
        .default(24 * 60 * ONE_MINUTE_MS)
        .describe(
            'Platform-wide floor for the `completed → closed` sweep. ' +
                'Agents that opt into `spec.resume.enabled` may extend this via `max_completed_age_ms`.'
        ),
    maxRetries: z.coerce.number().int().nonnegative().default(3).describe('Poison-pill threshold for re-queues.'),
    sweepIntervalMs: z.coerce
        .number()
        .int()
        .positive()
        .default(30 * 1000)
        .describe('How often the in-process sweep timer fires.'),
    memoryS3Endpoint: z
        .string()
        .url()
        .optional()
        .describe('S3 / MinIO endpoint for memory file storage. Unset disables the /memory/* routes (503).'),
    memoryS3Region: z.string().default('us-east-1').describe('Region for the memory bucket.'),
    memoryS3Bucket: z.string().optional().describe('Bucket holding agent memory files.'),
    memoryS3Prefix: z.string().default('agent_memory').describe('Per-deployment key prefix inside the bucket.'),
    memoryS3AccessKeyId: z
        .string()
        .optional()
        .describe('Optional explicit access key id; falls back to SDK default chain.'),
    memoryS3SecretAccessKey: z.string().optional().describe('Optional explicit secret access key.'),
    memoryS3ForcePathStyle: z
        .union([z.literal('1'), z.literal('0'), z.literal('true'), z.literal('false')])
        .default('1')
        .transform((v) => v === '1' || v === 'true')
        .describe('forcePathStyle for the S3 client. Default true (MinIO needs it).'),
})

export type AgentJanitorConfig = z.infer<typeof AgentJanitorConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentJanitorConfig>(PLATFORM_ENV_KEY_MAP, {
    PORT: 'port',
    INTERNAL_SECRET: 'internalSecret',
    STUCK_RUNNING_MS: 'stuckRunningMs',
    STUCK_WAITING_MS: 'stuckWaitingMs',
    IDLE_COMPLETED_MS: 'idleCompletedMs',
    MAX_RETRIES: 'maxRetries',
    SWEEP_INTERVAL_MS: 'sweepIntervalMs',
    AGENT_MEMORY_S3_ENDPOINT: 'memoryS3Endpoint',
    AGENT_MEMORY_S3_REGION: 'memoryS3Region',
    AGENT_MEMORY_S3_BUCKET: 'memoryS3Bucket',
    AGENT_MEMORY_S3_PREFIX: 'memoryS3Prefix',
    AGENT_MEMORY_S3_ACCESS_KEY_ID: 'memoryS3AccessKeyId',
    AGENT_MEMORY_S3_SECRET_ACCESS_KEY: 'memoryS3SecretAccessKey',
    AGENT_MEMORY_S3_FORCE_PATH_STYLE: 'memoryS3ForcePathStyle',
})

export function loadAgentJanitorConfig(env: NodeJS.ProcessEnv = process.env): AgentJanitorConfig {
    return loadConfigFromEnv(AgentJanitorConfigSchema, ENV_KEY_MAP, env)
}
