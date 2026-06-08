/**
 * Typed config loader for the agent console.
 *
 * Every env var the console reads goes through this schema. Server route
 * handlers and lib code import `getConfig()` rather than reaching for
 * `process.env` directly — same pattern as the other agent services
 * (`agent-ingress/src/config.ts`, etc.).
 *
 * Dev (`NODE_ENV !== 'production'`) gets safe defaults so `pnpm dev`
 * works without any env setup — including a deterministic
 * `OAUTH_COOKIE_SECRET` so sessions survive `next dev` restarts. Prod
 * fails fast at boot if any required value is missing or malformed.
 */

import { z } from 'zod'

export function isDev(env: NodeJS.ProcessEnv = process.env): boolean {
    return env.NODE_ENV !== 'production'
}

// Deterministic 32+ char dev cookie sealer. Same approach as
// agent-shared's DEV_ENCRYPTION_KEY: a constant local default so
// devs aren't forced to copy a value into .env.local and so sealed
// cookies survive `next dev` restarts. **Never used in production** —
// the schema requires the env var to be set when NODE_ENV=production.
const DEV_OAUTH_COOKIE_SECRET = 'agent-console-dev-cookie-secret-do-not-use-in-prod'

// Matches the deterministic client_id Django's
// `setup_oauth_for_agent_console` always uses.
const DEV_OAUTH_CLIENT_ID = 'agent-console-dev'

const stripTrailingSlash = (v: string): string => v.replace(/\/$/, '')

export const AgentConsoleConfigSchema = z.object({
    posthogBaseUrl: z
        .string()
        .url()
        .default(() => (isDev() ? 'http://localhost:8010' : ''))
        .transform(stripTrailingSlash)
        .describe('PostHog Django base URL. Required in prod; dev defaults to http://localhost:8010.'),
    posthogAgentsBaseUrl: z
        .string()
        .url()
        .default(() => (isDev() ? 'http://localhost:3030' : ''))
        .transform(stripTrailingSlash)
        .describe('agent-ingress base URL. Required in prod; dev defaults to http://localhost:3030.'),
    consoleBaseUrl: z
        .string()
        .url()
        .default('http://localhost:3040')
        .transform(stripTrailingSlash)
        .describe('Public URL the browser hits the console at. Used to build the OAuth redirect URI.'),
    oauthClientId: z
        .string()
        .default(() => (isDev() ? DEV_OAUTH_CLIENT_ID : ''))
        .describe(
            'OAuth client_id. Dev defaults to `agent-console-dev` (matches `python manage.py setup_oauth_for_agent_console`); prod supplied via ops.'
        ),
    oauthClientSecret: z
        .string()
        .default('')
        .describe(
            'OAuth client_secret. In dev, run `pnpm setup:local` to provision the app in Django and write this value into `.env.local`. Required in prod.'
        ),
    oauthCookieSecret: z
        .string()
        .default(() => (isDev() ? DEV_OAUTH_COOKIE_SECRET : ''))
        .describe(
            '32+ char string used to seal the HTTP-only session cookie. Dev defaults to a deterministic local key so sessions survive `next dev` restarts; prod must set explicitly.'
        ),
    nodeEnv: z
        .enum(['development', 'production', 'test'])
        .default('development')
        .describe('Node env. Controls cookie `secure` flag and the dev-default gating above.'),
})

export type AgentConsoleConfig = z.infer<typeof AgentConsoleConfigSchema>

const ENV_KEY_MAP: Record<string, keyof AgentConsoleConfig> = {
    POSTHOG_BASE_URL: 'posthogBaseUrl',
    POSTHOG_AGENTS_BASE: 'posthogAgentsBaseUrl',
    CONSOLE_BASE_URL: 'consoleBaseUrl',
    POSTHOG_OAUTH_CLIENT_ID: 'oauthClientId',
    POSTHOG_OAUTH_CLIENT_SECRET: 'oauthClientSecret',
    OAUTH_COOKIE_SECRET: 'oauthCookieSecret',
    NODE_ENV: 'nodeEnv',
}

// Fields with no safe prod default — empty values must fail closed at
// boot rather than silently producing broken behavior at request time.
const REQUIRED_IN_PROD: Array<keyof AgentConsoleConfig> = [
    'posthogBaseUrl',
    'posthogAgentsBaseUrl',
    'oauthClientId',
    'oauthClientSecret',
    'oauthCookieSecret',
]

const PROD_ENV_NAMES: Record<keyof AgentConsoleConfig, string> = {
    posthogBaseUrl: 'POSTHOG_BASE_URL',
    posthogAgentsBaseUrl: 'POSTHOG_AGENTS_BASE',
    consoleBaseUrl: 'CONSOLE_BASE_URL',
    oauthClientId: 'POSTHOG_OAUTH_CLIENT_ID',
    oauthClientSecret: 'POSTHOG_OAUTH_CLIENT_SECRET',
    oauthCookieSecret: 'OAUTH_COOKIE_SECRET',
    nodeEnv: 'NODE_ENV',
}

export function loadAgentConsoleConfig(env: NodeJS.ProcessEnv = process.env): AgentConsoleConfig {
    const raw: Record<string, string | undefined> = {}
    for (const [envName, schemaKey] of Object.entries(ENV_KEY_MAP)) {
        if (env[envName] !== undefined) {
            raw[schemaKey] = env[envName]
        }
    }
    const parsed = AgentConsoleConfigSchema.parse(raw)

    if (parsed.oauthCookieSecret && parsed.oauthCookieSecret.length < 32) {
        throw new Error('OAUTH_COOKIE_SECRET must be at least 32 characters')
    }

    if (parsed.nodeEnv === 'production') {
        const missing = REQUIRED_IN_PROD.filter((k) => !parsed[k])
        if (missing.length > 0) {
            const names = missing.map((k) => PROD_ENV_NAMES[k]).join(', ')
            throw new Error(`Missing required env vars in production: ${names}`)
        }
    }

    return parsed
}

let cached: AgentConsoleConfig | null = null

/**
 * Module-level singleton — loaded once per process. Route handlers and
 * lib modules call this instead of touching `process.env` themselves.
 */
export function getConfig(): AgentConsoleConfig {
    if (!cached) {
        cached = loadAgentConsoleConfig()
    }
    return cached
}

/** Test-only: reset the cached config so a follow-up `getConfig()` re-reads env. */
export function _resetConfigForTests(): void {
    cached = null
}
