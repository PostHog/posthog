import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import { GOOGLE_AUTHORIZE, GOOGLE_TOKEN, GOOGLE_TOKEN_INFO, GOOGLE_USERINFO_EMAIL_SCOPE } from './google'
import type { ProviderSpec } from './schema'

export const googleSheets: ProviderSpec = {
    kind: 'google-sheets',
    label: 'Google Sheets',
    authTypes: { default: 'oauth', others: ['credentials'] },
    authorize: {
        ...GOOGLE_AUTHORIZE,
        scope: `https://www.googleapis.com/auth/spreadsheets ${GOOGLE_USERINFO_EMAIL_SCOPE}`,
    },
    token: GOOGLE_TOKEN,
    // The Google sign-in app, not an app of its own.
    clientSecretKeys: {
        clientId: '__PROVIDER_SOCIAL_AUTH_GOOGLE_OAUTH2_KEY',
        clientSecret: '__PROVIDER_SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET',
    },
    identityConfigKeys: ['sub', 'email'],
    tokenInfo: GOOGLE_TOKEN_INFO,
    refresh: { ...OAUTH_REFRESH, mode: 'static' },
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: ['email'] },
}
