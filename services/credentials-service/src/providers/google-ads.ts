import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import { GOOGLE_AUTHORIZE, GOOGLE_TOKEN, GOOGLE_TOKEN_INFO, GOOGLE_USERINFO_EMAIL_SCOPE } from './google'
import type { ProviderSpec } from './schema'

export const googleAds: ProviderSpec = {
    kind: 'google-ads',
    label: 'Google Ads',
    authTypes: { default: 'oauth', others: [] },
    authorize: { ...GOOGLE_AUTHORIZE, scope: `https://www.googleapis.com/auth/adwords ${GOOGLE_USERINFO_EMAIL_SCOPE}` },
    token: GOOGLE_TOKEN,
    clientSecretKeys: {
        clientId: '__PROVIDER_GOOGLE_ADS_APP_CLIENT_ID',
        clientSecret: '__PROVIDER_GOOGLE_ADS_APP_CLIENT_SECRET',
    },
    identityConfigKeys: ['sub', 'email'],
    tokenInfo: GOOGLE_TOKEN_INFO,
    refresh: { ...OAUTH_REFRESH, mode: 'static' },
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: ['email'] },
}
