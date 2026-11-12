import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import type { ProviderSpec } from './schema'

export const salesforce: ProviderSpec = {
    kind: 'salesforce',
    label: 'Salesforce',
    authTypes: { default: 'oauth', others: [] },
    authorize: {
        url: 'https://login.salesforce.com/services/oauth2/authorize',
        scope: 'full refresh_token',
        pkce: true,
        opaqueState: false,
    },
    token: {
        url: 'https://login.salesforce.com/services/oauth2/token',
        revokeUrl: 'https://login.salesforce.com/services/oauth2/revoke',
        auth: 'client_secret_post',
        // A sandbox org authorizes at the production login page but redeems its code only at the
        // sandbox host. Its rows keep the `salesforce` kind.
        exchangeFallbackUrls: ['https://test.salesforce.com/services/oauth2/token'],
        // So a sandbox row refreshes and revokes at its own org, which the production host refuses.
        // Port of `_salesforce_instance_host`: https, no port, no credentials, a `.salesforce.com` host.
        tokenHost: {
            fromConfig: 'instance_url',
            allow: ['.salesforce.com'],
            tokenPath: '/services/oauth2/token',
            revokePath: '/services/oauth2/revoke',
        },
    },
    clientSecretKeys: {
        clientId: '__PROVIDER_SALESFORCE_CONSUMER_KEY',
        clientSecret: '__PROVIDER_SALESFORCE_CONSUMER_SECRET',
    },
    identityConfigKeys: ['instance_url'],
    tokenInfo: { idPath: 'instance_url', namePath: 'instance_url' },
    // Salesforce often sends no `expires_in`. Its tokens last 2 to 4 hours, so 1 hour is safe.
    // A connected app can turn on refresh token rotation, so the mode assumes it is on.
    refresh: { ...OAUTH_REFRESH, mode: 'rotating', defaultExpiresInSeconds: 3600 },
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: ['instance_url'] },
}
