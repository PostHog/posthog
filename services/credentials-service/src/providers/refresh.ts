// Refresh timing and failure classification. Ports of `access_token_expired`,
// `refresh_failure_patch` and `oauth_refresh_failure_reason` (`posthog/models/integration/`).

import { dotGet } from './paths'
import type { RefreshSpec } from './schema'

export type RefreshFailureReason =
    | 'invalid_grant'
    | 'invalid_client'
    | 'rate_limited'
    | 'http_5xx'
    | 'network'
    | 'other'
    | 'unreadable_secret'
    | 'invalid_token_uri'

/** Failures that say nothing about the grant. A caller must not mark the row for reconnect over one. */
export const TRANSIENT_REFRESH_FAILURES: ReadonlySet<RefreshFailureReason> = new Set([
    'http_5xx',
    'network',
    'rate_limited',
])

/**
 * When the scheduler refreshes the row next, or null when the row has no lifetime to track. A
 * provider that sends no `expires_in` falls back to the spec's default. As in Python, a zero
 * `expires_in` counts as absent.
 */
export function refreshDueAt(
    refresh: RefreshSpec | undefined,
    token: { refreshedAt: Date | null; expiresInSeconds: number | null }
): Date | null {
    if (!refresh || !token.refreshedAt) {
        return null
    }
    const expiresIn = token.expiresInSeconds || refresh.defaultExpiresInSeconds
    if (!expiresIn) {
        return null
    }
    return new Date(token.refreshedAt.getTime() + expiresIn * refresh.refreshAtLifetimeFraction * 1000)
}

/** The wait before the next attempt, after this many failures in a row (one or more). */
export function refreshBackoffSeconds(refresh: RefreshSpec, consecutiveFailures: number): number {
    const exponent = Math.max(consecutiveFailures, 1) - 1
    return Math.min(refresh.backoff.baseSeconds * 2 ** exponent, refresh.backoff.maxSeconds)
}

/** Bucket a failed refresh response. Only `invalid_grant` counts toward `terminalAfter`. */
export function classifyRefreshFailure(refresh: RefreshSpec, status: number, body: unknown): RefreshFailureReason {
    const error = dotGet(body, 'error')
    if (error === 'invalid_grant') {
        return 'invalid_grant'
    }
    if (error === 'invalid_client') {
        return 'invalid_client'
    }
    for (const matcher of refresh.terminalErrors) {
        if (matcher.status !== undefined && status !== matcher.status) {
            continue
        }
        if (matcher.statusBelow !== undefined && status >= matcher.statusBelow) {
            continue
        }
        if (dotGet(body, matcher.path) === matcher.equals) {
            return 'invalid_grant'
        }
    }
    // Throttling is not a credential problem. Treating it as one would sync failed rows into retry herds.
    if (status === 429) {
        return 'rate_limited'
    }
    if (status >= 500) {
        return 'http_5xx'
    }
    return 'other'
}

/**
 * Whether this failure makes the row terminal, so the scheduler stops and the UI asks for a
 * reconnect. A secret the service cannot read or a key file with a bad token URI never reached
 * the provider, so no retry can fix it. `invalid_grant` needs an unbroken streak, so one stray
 * `invalid_grant` in a 5xx outage cannot end a working grant. Other reasons never go terminal,
 * so a fix on PostHog's side lets every row recover.
 */
export function isTerminalFailure(
    refresh: RefreshSpec,
    reason: RefreshFailureReason,
    invalidGrantStreak: number
): boolean {
    if (reason === 'unreadable_secret' || reason === 'invalid_token_uri') {
        return true
    }
    return reason === 'invalid_grant' && invalidGrantStreak >= refresh.terminalAfter
}
