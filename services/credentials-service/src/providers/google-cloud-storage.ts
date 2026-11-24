import { ACCESS_TOKEN_ONLY, OAUTH_REFRESH } from './defaults'
import type { ProviderSpec } from './schema'

export const googleCloudStorage: ProviderSpec = {
    kind: 'google-cloud-storage',
    label: 'Google Cloud Storage',
    authTypes: { default: 'credentials', others: [] },
    // The customer uploads a service account key file. The service mints short-lived access tokens from it.
    mint: {
        type: 'google_sa_jwt',
        scope: 'https://www.googleapis.com/auth/devstorage.read_write',
        keyField: 'key_info',
        // The only token endpoints that Google writes into a key file. Any other value is hand-edited.
        tokenUriAllowlist: ['https://oauth2.googleapis.com/token', 'https://accounts.google.com/o/oauth2/token'],
    },
    // The key file is a secret field, so the row has no identity config.
    identityConfigKeys: [],
    // A new token is minted from the key file, so a retry is always safe.
    refresh: { ...OAUTH_REFRESH, mode: 'static' },
    // Callers get the minted token only. The key file stays in the service.
    resolveExposes: ACCESS_TOKEN_ONLY,
    displayName: { configPaths: [], whenMissing: 'unknown ID' },
}
