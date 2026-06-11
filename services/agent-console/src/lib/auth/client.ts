/**
 * OAuth client config — pulls from the typed config.
 *
 * The agent console doesn't self-register. The OAuth app is provisioned
 * out-of-band:
 *   - **Dev:** `python manage.py setup_oauth_for_agent_console` (also
 *     wrapped by `pnpm setup:local`) creates the OAuthApplication row
 *     and writes credentials into `.env.local`.
 *   - **Prod:** ops creates the OAuth app via the PostHog admin and
 *     supplies `POSTHOG_OAUTH_CLIENT_ID` + `POSTHOG_OAUTH_CLIENT_SECRET`
 *     via the deploy's env.
 *
 * Scopes are requested up-front to avoid re-prompting consent when we
 * add the write surface later.
 */

import { getConfig } from '@/lib/config'

export interface OAuthClient {
    clientId: string
    clientSecret: string
}

const SCOPES = [
    'openid',
    'user:read',
    'organization:read',
    'project:read',
    'agents:read',
    'agents:write',
    // Temporarily disabled: the dev-two deploy runs the agent-platform-django-base
    // image, which doesn't ship the `ai_gateway` scope yet, so requesting it makes
    // /oauth/authorize fail with invalid_scope. Re-enable once the ai-gateway slice
    // lands in that image.
    // 'ai_gateway:read',
    // Read-only HogQL over the team's own events — powers the analytics
    // dashboard's rollups over the agents' `$ai_*` observability events.
    'query:read',
].join(' ')

export function getOAuthClient(): OAuthClient {
    const { oauthClientId, oauthClientSecret } = getConfig()
    if (!oauthClientId || !oauthClientSecret) {
        throw new Error(
            'POSTHOG_OAUTH_CLIENT_ID / POSTHOG_OAUTH_CLIENT_SECRET are not set. Run `pnpm --filter @posthog/agent-console setup:local` to provision a dev OAuth app.'
        )
    }
    return { clientId: oauthClientId, clientSecret: oauthClientSecret }
}

export function clientScope(): string {
    return SCOPES
}

export function redirectUri(): string {
    return new URL('/api/auth/callback', getConfig().consoleBaseUrl).toString()
}
