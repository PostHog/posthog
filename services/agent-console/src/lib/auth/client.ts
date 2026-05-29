/**
 * OAuth client config — env-var driven.
 *
 * The agent console doesn't self-register. The OAuth app is provisioned
 * out-of-band:
 *   - **Dev:** `python manage.py setup_oauth_for_agent_console` (added
 *     in the same change as this file) creates the OAuthApplication
 *     row and prints credentials to paste into `.env.local`.
 *   - **Prod:** ops creates the OAuth app via the PostHog admin and
 *     supplies `POSTHOG_OAUTH_CLIENT_ID` + `POSTHOG_OAUTH_CLIENT_SECRET`
 *     via the deploy's env.
 *
 * Scopes are requested up-front to avoid re-prompting consent when we
 * add the write surface later.
 */

import { consoleBaseUrl } from './config'

export interface OAuthClient {
    clientId: string
    clientSecret: string
}

const SCOPES = [
    'openid',
    'user:read',
    'organization:read',
    'project:read',
    'agent_application:read',
    'agent_application:write',
    'ai_gateway:read',
].join(' ')

export function getOAuthClient(): OAuthClient {
    const clientId = process.env.POSTHOG_OAUTH_CLIENT_ID
    const clientSecret = process.env.POSTHOG_OAUTH_CLIENT_SECRET
    if (!clientId || !clientSecret) {
        throw new Error(
            'POSTHOG_OAUTH_CLIENT_ID / POSTHOG_OAUTH_CLIENT_SECRET are not set. Run `python manage.py setup_oauth_for_agent_console` to provision a dev OAuth app, then paste the values into services/agent-console/.env.local.'
        )
    }
    return { clientId, clientSecret }
}

export function clientScope(): string {
    return SCOPES
}

export function redirectUri(): string {
    return new URL('/api/auth/callback', consoleBaseUrl()).toString()
}
