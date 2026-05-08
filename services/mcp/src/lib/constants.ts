import { env } from 'cloudflare:workers'

import type { CloudRegion } from '@/tools/types'

import packageJson from '../../package.json'

export const USER_AGENT = `posthog/mcp-server; version: ${packageJson.version}`

export interface GetUserAgentOptions {
    clientUserAgent?: string | undefined
}

export function getUserAgent(opts: GetUserAgentOptions = {}): string {
    const { clientUserAgent } = opts

    if (clientUserAgent) {
        const match = clientUserAgent.match(/posthog\/([\w.-]+)/)
        if (match) {
            return `${USER_AGENT}; for ${match[0]}`
        }
    }

    return USER_AGENT
}

// Region-specific PostHog API base URLs
export const POSTHOG_US_BASE_URL = 'https://us.posthog.com'
export const POSTHOG_EU_BASE_URL = 'https://eu.posthog.com'

// Normalize a string to a valid CloudRegion, defaulting to 'us'
export const toCloudRegion = (value: string | undefined | null): CloudRegion => {
    const normalized = value?.toLowerCase()
    if (normalized === 'eu') {
        return 'eu'
    }
    return 'us'
}

// Get the PostHog base URL for a region
export const getBaseUrlForRegion = (region: CloudRegion): string => {
    return region === 'eu' ? POSTHOG_EU_BASE_URL : POSTHOG_US_BASE_URL
}

/**
 * Custom API base URL for self-hosted PostHog instances.
 *
 * WARNING: In PostHog Production, this should NOT be set.
 * The code automatically handles US/EU region routing via getAuthorizationServerUrl().
 * Only set this for self-hosted PostHog deployments.
 */
export const CUSTOM_API_BASE_URL = env.POSTHOG_API_BASE_URL

const OAUTH_PROXY_URL = 'https://oauth.posthog.com'

// Get the authorization server URL for OAuth
// Uses the cross-region OAuth proxy for cloud, or CUSTOM_API_BASE_URL for self-hosted
export const getAuthorizationServerUrl = (): string => {
    if (CUSTOM_API_BASE_URL) {
        return CUSTOM_API_BASE_URL
    }

    return OAUTH_PROXY_URL
}

// OAuth Authorization Server URL (where clients get tokens)
// Defaults to CUSTOM_API_BASE_URL if not explicitly set
export const OAUTH_AUTHORIZATION_SERVER_URL =
    (env as unknown as Record<string, string | undefined>).OAUTH_AUTHORIZATION_SERVER_URL || CUSTOM_API_BASE_URL

export const MCP_DOCS_URL = 'https://posthog.com/docs/model-context-protocol'

// OAuth Protected Resource Metadata (RFC 9728). Generated from posthog/scopes.py
// to match what the authorization server actually advertises. See
// oauth-scopes.generated.ts and bin/build-mcp-oauth-scopes.py.
export { OAUTH_SCOPES_SUPPORTED, type OAuthScope } from './oauth-scopes.generated'
