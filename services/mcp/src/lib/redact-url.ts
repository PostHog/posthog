// Session-recording URLs (`start_url`) are the raw first `href` captured by the browser SDK,
// truncated only for length. If an app embeds credentials in query params or URL fragments
// (magic links, OAuth implicit-flow `#access_token=...`, `?api_key=...`), those values would flow
// verbatim into MCP tool output, and from there into scout summaries, feedback events, and agent
// logs. We redact the *values* of credential-like keys while preserving the URL path and the key
// names, so the output stays useful for debugging without leaking secrets.

const REDACTED = '[REDACTED]'

// Matched against each token of a param key (split on non-alphanumerics and camelCase humps),
// case-insensitively. Token-level matching avoids over-redacting a key that merely contains a
// sensitive substring (e.g. `keyword` does not match `key`, `insight` does not match `sig`).
const SENSITIVE_KEY_TOKENS = new Set([
    'token',
    'key',
    'apikey',
    'secret',
    'password',
    'passwd',
    'pwd',
    'auth',
    'authorization',
    'bearer',
    'credential',
    'credentials',
    'session',
    'sessionid',
    'sid',
    'sig',
    'signature',
    'hmac',
    'otp',
    'jwt',
])

function keyTokens(key: string): string[] {
    let decoded = key
    try {
        decoded = decodeURIComponent(key.replace(/\+/g, ' '))
    } catch {
        // Malformed percent-encoding: fall back to the raw key text.
    }
    return decoded
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2') // split camelCase humps
        .split(/[^a-zA-Z0-9]+/)
        .filter(Boolean)
        .map((token) => token.toLowerCase())
}

function isSensitiveKey(key: string): boolean {
    return keyTokens(key).some((token) => SENSITIVE_KEY_TOKENS.has(token))
}

// Redact the values of credential-like keys in a `&`-separated `key=value` list, preserving the key
// text and every non-sensitive pair verbatim.
function redactPairs(pairs: string): string {
    return pairs
        .split('&')
        .map((pair) => {
            const eq = pair.indexOf('=')
            if (eq === -1) {
                return pair
            }
            const key = pair.slice(0, eq)
            const value = pair.slice(eq + 1)
            if (value !== '' && isSensitiveKey(key)) {
                return `${key}=${REDACTED}`
            }
            return pair
        })
        .join('&')
}

// Redact credential-like query-parameter and fragment values from a URL, keeping the scheme, host,
// path, and parameter names intact. Non-URL / empty input is returned unchanged.
export function redactSensitiveUrl(url: string): string {
    if (typeof url !== 'string' || url === '') {
        return url
    }
    const hashIdx = url.indexOf('#')
    const fragment = hashIdx === -1 ? '' : url.slice(hashIdx + 1)
    const beforeHash = hashIdx === -1 ? url : url.slice(0, hashIdx)
    const qIdx = beforeHash.indexOf('?')
    const base = qIdx === -1 ? beforeHash : beforeHash.slice(0, qIdx)
    const query = qIdx === -1 ? '' : beforeHash.slice(qIdx + 1)

    let out = base
    if (qIdx !== -1) {
        out += `?${redactPairs(query)}`
    }
    if (hashIdx !== -1) {
        // Only treat a fragment as redactable when it looks like a `key=value` list (e.g. the OAuth
        // implicit-flow `#access_token=...`); a plain anchor like `#section-2` is left untouched.
        out += `#${fragment.includes('=') ? redactPairs(fragment) : fragment}`
    }
    return out
}

// Redact the `start_url` of each recording in a RecordingsQuery result set. For that query kind the
// backend returns `results` as an array of recording objects, each with a raw `start_url`.
export function redactRecordingUrls(results: unknown): unknown {
    if (!Array.isArray(results)) {
        return results
    }
    return results.map((recording) => {
        if (recording && typeof recording === 'object' && 'start_url' in recording) {
            const { start_url: startUrl } = recording as { start_url?: unknown }
            if (typeof startUrl === 'string') {
                return { ...recording, start_url: redactSensitiveUrl(startUrl) }
            }
        }
        return recording
    })
}
