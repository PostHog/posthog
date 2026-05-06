// Runtime-agnostic OAuth/region constants shared between the Cloudflare Workers
// and Hono entry points. No imports from `cloudflare:workers` or Node-only modules
// so this file is safe to import from either runtime.

import type { CloudRegion } from '@/tools/types'

import packageJson from '../../package.json'

export const USER_AGENT = `posthog/mcp-server; version: ${packageJson.version}`

export interface GetUserAgentOptions {
    clientUserAgent?: string | undefined
    /** `x-posthog-mcp-consumer` — self-identifier of the wrapping app (e.g. `posthog-code`, `slack`). */
    mcpConsumer?: string | undefined
    /** MCP `clientInfo.name` — the wrapped client (e.g. `claude-code`). */
    mcpClientName?: string | undefined
}

export function getUserAgent(opts: GetUserAgentOptions = {}): string {
    const { clientUserAgent, mcpConsumer, mcpClientName } = opts
    const parts: string[] = []

    // When the caller self-identifies as a wrapping consumer app, emit
    // `<consumer>/<wrapped-client>` as the leading UA token so downstream
    // services can attribute traffic without parsing custom headers.
    if (mcpConsumer) {
        const wrappedClient = (mcpClientName || 'unknown').replace(/\s+/g, '-')
        parts.push(`${mcpConsumer}/${wrappedClient}`)
    }

    parts.push(USER_AGENT)

    if (clientUserAgent) {
        const match = clientUserAgent.match(/posthog\/([\w.-]+)/)
        if (match) {
            parts[parts.length - 1] = `${USER_AGENT}; for ${match[0]}`
        }
    }

    return parts.join(' ')
}

export const POSTHOG_US_BASE_URL = 'https://us.posthog.com'
export const POSTHOG_EU_BASE_URL = 'https://eu.posthog.com'

export const toCloudRegion = (value: string | undefined | null): CloudRegion => {
    const normalized = value?.toLowerCase()
    if (normalized === 'eu') {
        return 'eu'
    }
    return 'us'
}

export const getBaseUrlForRegion = (region: CloudRegion): string => {
    return region === 'eu' ? POSTHOG_EU_BASE_URL : POSTHOG_US_BASE_URL
}

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'

export const OAUTH_PROXY_URL = 'https://oauth.posthog.com'

// Resolve the OAuth authorization server URL given an optional self-hosted override.
// Each runtime fetches the override from its own env source (CF binding vs process.env)
// and passes it in.
export const resolveAuthorizationServerUrl = (customApiBaseUrl: string | undefined): string => {
    return customApiBaseUrl || OAUTH_PROXY_URL
}

// Generated from `posthog/scopes.py` — keep in sync with `hogli build:openapi`.
export { OAUTH_SCOPES_SUPPORTED, type OAuthScope } from './oauth-scopes.generated'
