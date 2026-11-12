import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import type { ProviderSpec } from './schema'

export const linear: ProviderSpec = {
    kind: 'linear',
    label: 'Linear',
    authTypes: { default: 'oauth', others: [] },
    authorize: {
        url: 'https://linear.app/oauth/authorize',
        scope: 'read issues:create',
        // Linear skips its approval screen once the app is authorized, and that screen holds the
        // only workspace switcher. Without `prompt=consent`, a person in several workspaces can
        // connect only the first one.
        extraParams: [
            ['actor', 'application'],
            ['prompt', 'consent'],
        ],
        pkce: false,
        opaqueState: false,
    },
    token: { url: 'https://api.linear.app/oauth/token', auth: 'client_secret_post' },
    clientSecretKeys: {
        clientId: '__PROVIDER_LINEAR_APP_CLIENT_ID',
        clientSecret: '__PROVIDER_LINEAR_APP_CLIENT_SECRET',
    },
    identityConfigKeys: [
        'data',
        'data.viewer.organization.id',
        'data.viewer.organization.name',
        'data.viewer.organization.urlKey',
    ],
    tokenInfo: {
        idPath: 'data.viewer.organization.id',
        namePath: 'data.viewer.organization.name',
        request: {
            url: 'https://api.linear.app/graphql',
            graphqlQuery: '{ viewer { organization { id name urlKey } } }',
            configFields: [
                'data.viewer.organization.id',
                'data.viewer.organization.name',
                'data.viewer.organization.urlKey',
            ],
        },
    },
    refresh: { ...OAUTH_REFRESH, mode: 'rotating' },
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: ['data.viewer.organization.name'] },
}
