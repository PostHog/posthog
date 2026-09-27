/**
 * Masks credential-shaped query parameter values in analytics results.
 *
 * Captured URL properties (`$current_url`, `$pathname`, `$referrer`, and
 * whatever an application stores) often keep the query string of an OAuth
 * callback, a magic link, or a signed download. A tool result enters the agent
 * transcript, so a live authorization code or token in it can be stored and
 * repeated. The parameter name and the rest of the URL stay, so an agent can
 * still group and diagnose events by URL.
 *
 * This is a client-boundary safeguard. Stored events and the PostHog UI keep
 * the complete value.
 */

import { assignKey, isRecord } from '@/lib/plain-object'

const REDACTED_VALUE = '[REDACTED]'

/** Names that carry a credential only as the whole parameter name. */
const EXACT_CREDENTIAL_NAMES = new Set(['code', 'state', 'key', 'sig', 'auth', 'jwt', 'otp', 'ticket', 'nonce'])

/**
 * Suffixes that mark a credential in any compound name, such as `access_token`,
 * `client_secret`, `X-Amz-Signature`, or `apiKey`.
 */
const CREDENTIAL_NAME_SUFFIX =
    /(?:token|secret|password|passwd|signature|credential|credentials|api_?key|access_?key)$/i

/**
 * A parameter starts after `?`, `&`, `#`, or `;`, or after their percent-encoded
 * forms when a URL sits inside another parameter (a `redirect_uri`, for
 * example). The value stops at the next delimiter, or at a character that
 * cannot be part of a URL in CSV, JSON, or table output.
 */
const QUERY_PARAMETER = /((?:[?&#;]|%3F|%26|%23)([\w.\-[\]]+)(?:=|%3D))((?:(?!%26|%23|%3F)[^&#;\s"'<>,|\\`])+)/gi

function isCredentialName(name: string): boolean {
    const normalized = name.replace(/\[\]$/, '').toLowerCase()
    return EXACT_CREDENTIAL_NAMES.has(normalized) || CREDENTIAL_NAME_SUFFIX.test(normalized)
}

export function redactUrlCredentials(text: string): string {
    if (!text.includes('=') && !/%3D/i.test(text)) {
        return text
    }
    return text.replace(QUERY_PARAMETER, (match, prefix: string, name: string) =>
        isCredentialName(name) ? `${prefix}${REDACTED_VALUE}` : match
    )
}

/** Apply `redactUrlCredentials` to every string in a parsed JSON value. */
export function redactUrlCredentialsDeep<T>(value: T): T {
    return redactValue(value) as T
}

function redactValue(value: unknown): unknown {
    if (typeof value === 'string') {
        return redactUrlCredentials(value)
    }
    if (Array.isArray(value)) {
        return value.map(redactValue)
    }
    if (isRecord(value)) {
        const out: Record<string, unknown> = {}
        for (const [key, entry] of Object.entries(value)) {
            assignKey(out, redactUrlCredentials(key), redactValue(entry))
        }
        return out
    }
    return value
}
