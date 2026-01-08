import { env } from 'cloudflare:workers'

export const CUSTOM_BASE_URL = env.POSTHOG_BASE_URL

// OAuth Authorization Server URL (where clients get tokens)
// Defaults to app.posthog.com but can be overridden for local dev
export const OAUTH_AUTHORIZATION_SERVER_URL =
    (env as unknown as Record<string, string | undefined>).OAUTH_AUTHORIZATION_SERVER_URL || 'https://app.posthog.com'

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'
