// Values that several specs share, so a change to PostHog's refresh policy is one edit.

import type { RefreshSpec } from './schema'

/**
 * The refresh policy of `refresh_tracking.py`: refresh at half the token lifetime, back off
 * 2 minutes doubling up to an hour, and go terminal after 5 `invalid_grant` failures in a row.
 */
export const OAUTH_REFRESH: Omit<RefreshSpec, 'mode'> = {
    refreshAtLifetimeFraction: 0.5,
    backoff: { baseSeconds: 120, maxSeconds: 3600 },
    terminalAfter: 5,
    terminalErrors: [],
}

/**
 * Platform secrets that only the provider registry reads (client secrets, minter keys) carry this
 * prefix. `/v1/secrets/resolve` never serves it. After the prefix comes the name that Django
 * settings and the platform secret mount use today, for example `SLACK_APP_CLIENT_SECRET` becomes
 * `__PROVIDER_SLACK_APP_CLIENT_SECRET`.
 */
export const PROVIDER_SECRET_PREFIX = '__PROVIDER_'

/** The name of a provider secret in the Django settings, the Python catalogue and the old mount. */
export function legacySecretName(providerSecretKey: string): string {
    return providerSecretKey.startsWith(PROVIDER_SECRET_PREFIX)
        ? providerSecretKey.slice(PROVIDER_SECRET_PREFIX.length)
        : providerSecretKey
}

/** The one secret field that `/resolve` returns for a plain OAuth kind. */
export const ACCESS_TOKEN_ONLY = ['access_token']
