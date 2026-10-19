/**
 * Masks credential values in free-form text before it reaches an MCP client.
 *
 * A log body is whatever the application wrote, and applications log request
 * URLs and form bodies verbatim, often JSON-encoded inside the message. A
 * response field filter cannot reach a credential that sits inside a string, so
 * this walks every string in a response and rewrites two shapes:
 *
 * - The value of a query or form parameter with a credential-shaped name. The
 *   host, the path and the parameter name stay, so a URL stays useful for triage.
 * - A PostHog personal, secret or OAuth token, wherever it appears.
 */

import { assignKey, isRecord } from '@/lib/plain-object'

const REDACTED_VALUE = '[REDACTED]'

/** Compared after the name is lowercased and stripped of everything but letters and digits. */
const CREDENTIAL_NAME_FRAGMENTS = ['apikey', 'token', 'secret', 'password', 'passwd', 'credential', 'signature']
const CREDENTIAL_NAMES = new Set(['key', 'pwd', 'auth', 'authorization', 'sig', 'code', 'jwt', 'session', 'sessionid'])

/**
 * A parameter starts after `?`, `&` or `;`, the percent-encoded `?` or `&` of a
 * nested URL, the start of the text, or a quote or space before a bare form body.
 * Its value ends at the next separator, quote, backslash or whitespace, so it
 * also ends correctly inside a JSON-encoded or escaped string.
 */
const PARAMETER_PATTERN = /((?:^|[?&;\s"'\\]|%3F|%26)([A-Za-z0-9_.\-[\]]+)(?:=|%3D))((?:(?!%26)[^&;\s"'\\#<>,])+)/gi

/**
 * PostHog token prefixes from `posthog/models/utils.py`: personal API keys,
 * secret API keys, OAuth access tokens and OAuth refresh tokens. The project
 * token `phc_` is public, so it stays.
 */
const POSTHOG_TOKEN_PATTERN = /\b(phx|phs|pha|phr)_[A-Za-z0-9_-]{16,}/g

function isCredentialName(name: string): boolean {
    const normalized = name.toLowerCase().replace(/[^a-z0-9]/g, '')
    return CREDENTIAL_NAMES.has(normalized) || CREDENTIAL_NAME_FRAGMENTS.some((part) => normalized.includes(part))
}

export function redactCredentialsInText(text: string): string {
    return text
        .replace(PARAMETER_PATTERN, (match, prefix: string, name: string, value: string) =>
            isCredentialName(name) && value !== REDACTED_VALUE ? `${prefix}${REDACTED_VALUE}` : match
        )
        .replace(POSTHOG_TOKEN_PATTERN, (_match, prefix: string) => `${prefix}_${REDACTED_VALUE}`)
}

/** Return a copy of a parsed JSON value with credential values masked in every string, keys included. */
export function redactCredentials(value: unknown): unknown {
    if (typeof value === 'string') {
        return redactCredentialsInText(value)
    }
    if (Array.isArray(value)) {
        return value.map(redactCredentials)
    }
    if (isRecord(value)) {
        const redacted: Record<string, unknown> = {}
        for (const [key, entry] of Object.entries(value)) {
            assignKey(redacted, redactCredentialsInText(key), redactCredentials(entry))
        }
        return redacted
    }
    return value
}
