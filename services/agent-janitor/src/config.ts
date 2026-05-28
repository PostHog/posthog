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
    maxRetries: z.coerce.number().int().nonnegative().default(3).describe('Poison-pill threshold for re-queues.'),
    sweepIntervalMs: z.coerce
        .number()
        .int()
        .positive()
        .default(30 * 1000)
        .describe('How often the in-process sweep timer fires.'),
})

export type AgentJanitorConfig = z.infer<typeof AgentJanitorConfigSchema>

const ENV_KEY_MAP = extendEnvKeyMap<AgentJanitorConfig>(PLATFORM_ENV_KEY_MAP, {
    PORT: 'port',
    INTERNAL_SECRET: 'internalSecret',
    STUCK_RUNNING_MS: 'stuckRunningMs',
    STUCK_WAITING_MS: 'stuckWaitingMs',
    MAX_RETRIES: 'maxRetries',
    SWEEP_INTERVAL_MS: 'sweepIntervalMs',
})

export function loadAgentJanitorConfig(env: NodeJS.ProcessEnv = process.env): AgentJanitorConfig {
    return loadConfigFromEnv(AgentJanitorConfigSchema, ENV_KEY_MAP, env)
}
