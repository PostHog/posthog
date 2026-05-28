/**
 * Typed configuration loader for the janitor.
 *
 * This is the **pilot** for the agent-services typed-config pattern (see
 * `docs/agent-platform/plans/typed-config-loader.md`). Every other process
 * env read in this package should go through here — the lint rule in
 * `eslint.config.js` enforces it.
 *
 * Why: prevents NaN-from-bad-int-parse from leaking into the runtime,
 * gives a single place to declare defaults, and prepares the generated
 * deploy-runbook (every field's `.describe()` becomes a runbook row).
 */

import { z } from 'zod'

const ONE_MINUTE_MS = 60_000

export const AgentJanitorConfigSchema = z.object({
    port: z.coerce.number().int().positive().default(8082).describe('HTTP listen port.'),
    posthogDbUrl: z
        .string()
        .url()
        .default('postgres://posthog:posthog@localhost:5432/posthog')
        .describe('Django/PostHog DB — reads agent_application + agent_revision for /revisions/*.'),
    agentDbUrl: z
        .string()
        .url()
        .default('postgres://posthog:posthog@localhost:5432/agent_runtime_queue')
        .describe('Queue + sandbox-instances DB — janitor sweep reaps stuck rows here.'),
    bundleRoot: z
        .string()
        .min(1)
        .default(`${process.env.HOME ?? '/tmp'}/.posthog/agent-bundles`)
        .describe(
            'Filesystem root for bundles. Auto-created on boot. Production sets this to a mounted volume shared with the runner.'
        ),
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
    logLevel: z
        .enum(['debug', 'info', 'warn', 'error', 'fatal'])
        .default('info')
        .describe('pino level. Set debug to trace per-sweep / per-request detail.'),
})

export type AgentJanitorConfig = z.infer<typeof AgentJanitorConfigSchema>

/**
 * Map UPPER_SNAKE env var name → camelCase schema key. Kept exhaustive so the
 * generated runbook script (a follow-up plan) walks it instead of the schema
 * shape directly.
 */
const ENV_KEY_MAP: Record<string, keyof AgentJanitorConfig> = {
    PORT: 'port',
    POSTHOG_DB_URL: 'posthogDbUrl',
    AGENT_DB_URL: 'agentDbUrl',
    AGENT_BUNDLE_ROOT: 'bundleRoot',
    INTERNAL_SECRET: 'internalSecret',
    STUCK_RUNNING_MS: 'stuckRunningMs',
    STUCK_WAITING_MS: 'stuckWaitingMs',
    MAX_RETRIES: 'maxRetries',
    SWEEP_INTERVAL_MS: 'sweepIntervalMs',
    LOG_LEVEL: 'logLevel',
}

/**
 * Read env (defaults: `process.env`) and parse into a typed `AgentJanitorConfig`.
 * Throws a zod error at boot if anything's malformed — much better than a
 * NaN leaking into a setInterval. Tests pass an explicit env object to avoid
 * process-state leakage between cases.
 */
export function loadAgentJanitorConfig(env: NodeJS.ProcessEnv = process.env): AgentJanitorConfig {
    const raw: Record<string, string | undefined> = {}
    for (const [envName, schemaKey] of Object.entries(ENV_KEY_MAP)) {
        if (env[envName] !== undefined) {
            raw[schemaKey] = env[envName]
        }
    }
    return AgentJanitorConfigSchema.parse(raw)
}
