import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import type { ProviderSpec } from './schema'

// `SlackIntegrationScope` in `posthog/schema_enums.py`, in its order. Every scope is approved for the public app.
const SCOPES = [
    'app_mentions:read',
    'assistant:write',
    'canvases:write',
    'channels:history',
    'channels:manage',
    'channels:read',
    'chat:write',
    'chat:write.customize',
    'commands',
    'files:read',
    'files:write',
    'groups:history',
    'groups:read',
    'im:history',
    'links:read',
    'links:write',
    'mpim:history',
    'mpim:read',
    'reactions:read',
    'reactions:write',
    'team:read',
    'users:read',
    'users:read.email',
]

// `SlackIntegrationScopeInReview`: Slack has not approved these for the public app, so only dev asks for them.
const SCOPES_IN_REVIEW = ['canvases:read', 'channels:join']

export const slack: ProviderSpec = {
    kind: 'slack',
    label: 'Slack',
    authTypes: { default: 'oauth', others: ['token'] },
    authorize: {
        url: 'https://slack.com/oauth/v2/authorize',
        // Slack takes comma-separated scopes.
        scope: SCOPES.join(','),
        pkce: false,
        opaqueState: false,
    },
    token: { url: 'https://slack.com/api/oauth.v2.access', auth: 'client_secret_post' },
    clientSecretKeys: {
        clientId: '__PROVIDER_SLACK_APP_CLIENT_ID',
        clientSecret: '__PROVIDER_SLACK_APP_CLIENT_SECRET',
    },
    identityConfigKeys: ['team'],
    tokenInfo: { idPath: 'team.id', namePath: 'team.name' },
    overrides: {
        environment: { dev: { authorize: { scope: [...SCOPES, ...SCOPES_IN_REVIEW].join(',') } } },
    },
    // A bot token without token rotation has no refresh token and no expiry, so it never comes due.
    refresh: { ...OAUTH_REFRESH, mode: 'rotating' },
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: ['team.name'] },
}
