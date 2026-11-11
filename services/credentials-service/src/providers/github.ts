import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import type { ProviderSpec } from './schema'

export const github: ProviderSpec = {
    kind: 'github',
    label: 'GitHub',
    authTypes: { default: 'oauth', others: ['token'] },
    // A GitHub App install, not an OAuth code grant: GitHub sends back an installation id, and the
    // service mints installation tokens with the App key. So the kind has no token endpoint.
    authorize: {
        url: 'https://github.com/apps/{app_slug}/installations/new',
        scope: '',
        params: [['state', '{state}']],
        pkce: false,
        opaqueState: false,
        urlValues: { app_slug: 'GITHUB_APP_SLUG' },
    },
    mint: {
        type: 'github_installation_token',
        appIdKey: '__PROVIDER_GITHUB_APP_CLIENT_ID',
        privateKeyKey: '__PROVIDER_GITHUB_APP_PRIVATE_KEY',
        installationIdField: 'installation_id',
    },
    identityConfigKeys: ['installation_id', 'account'],
    // Installation tokens last an hour. Minting again is always safe.
    refresh: { ...OAUTH_REFRESH, mode: 'static' },
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: ['account.name'] },
}
