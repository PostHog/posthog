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

/** The one secret field that `/resolve` returns for a plain OAuth kind. */
export const ACCESS_TOKEN_ONLY = ['access_token']
