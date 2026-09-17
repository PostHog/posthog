const REDACTED = '[redacted]'

/**
 * Parameter names whose value is a credential or a personal identifier. Matched as substrings
 * of the name with separators removed, so `access-token`, `access_token` and `accessToken`
 * all hit the `token` needle.
 */
const SENSITIVE_NAME_PARTS = [
    'token',
    'secret',
    'password',
    'passwd',
    'passcode',
    'apikey',
    'accesskey',
    'secretkey',
    'privatekey',
    'signingkey',
    'authorization',
    'credential',
    'signature',
    'email',
    'jwt',
    'bearer',
    'otp',
]

/** Names that are credentials on their own, but read as false positives inside longer words. */
const SENSITIVE_NAMES = new Set(['auth', 'oauth', 'code', 'sig', 'pass', 'pwd'])

/** `scheme://user:password@host`, where the credentials sit before the first `/`, `?`, `#` or `@`. */
const USERINFO = /^([a-z][a-z0-9+.-]*:\/\/)[^/?#@]*@/i

/** One `name=value` pair of a query string or a query-shaped fragment. */
const PARAM = /([^&=]+)=([^&]*)/g

const EMAIL = /[\w.%+-]+(?:@|%40)[\w-]+(?:\.[\w-]+)+/gi

/** Credential formats recognizable from the value alone, wherever they appear in the URL. */
const CREDENTIAL_VALUES = [
    /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}[A-Za-z0-9_.-]*/g, // JWT
    /gh[pousr]_[A-Za-z0-9]{16,}/g, // GitHub
    /sk-[A-Za-z0-9_-]{16,}/g,
    /xox[abeoprs]-[A-Za-z0-9-]{10,}/g, // Slack
    /AKIA[0-9A-Z]{16}/g, // AWS access key ID
    /ph[sx]_[A-Za-z0-9]{16,}/g, // PostHog secret key
]

const OPAQUE_RUN = /^[A-Za-z0-9._~+-]{20,}$/

/**
 * A fragment that carries no `name=value` pair but is one long opaque run of letters and
 * digits. An implicit-flow access token lands here. A fragment an agent can use, such as a
 * heading anchor or a client-side route, is shorter, holds a `/`, or reads as words with no
 * digits in it.
 */
function isOpaqueFragment(fragment: string): boolean {
    return OPAQUE_RUN.test(fragment) && /\d/.test(fragment) && /[A-Za-z]/.test(fragment)
}

function isSensitiveName(name: string): boolean {
    const normalized = decodeParamName(name)
        .toLowerCase()
        .replace(/[^a-z0-9]/g, '')
    return SENSITIVE_NAMES.has(normalized) || SENSITIVE_NAME_PARTS.some((part) => normalized.includes(part))
}

function decodeParamName(name: string): string {
    try {
        return decodeURIComponent(name.replace(/\+/g, ' '))
    } catch {
        // A stray `%` makes the name undecodable; match against the raw form instead.
        return name
    }
}

function redactParams(params: string): string {
    return params.replace(PARAM, (pair, name: string, value: string) =>
        value !== '' && isSensitiveName(name) ? `${name}=${REDACTED}` : pair
    )
}

function redactCredentialValues(url: string): string {
    let redacted = url.replace(EMAIL, REDACTED)
    for (const pattern of CREDENTIAL_VALUES) {
        redacted = redacted.replace(pattern, REDACTED)
    }
    return redacted
}

/**
 * Replace the credentials and personal identifiers a URL carries with `[redacted]`, keeping the
 * rest of it readable.
 *
 * URLs captured from a user's browser reach an agent as recording and event metadata. They
 * routinely carry an OAuth callback's authorization code, a magic-link token, or the signed-in
 * user's email address, and an agent's transcript keeps whatever the tool returned.
 *
 * The origin, the path and every other parameter survive, because that is what an agent reads
 * the URL for.
 */
export function redactUrlSecrets(url: string): string {
    if (!url) {
        return url
    }

    const hashAt = url.indexOf('#')
    const fragment = hashAt === -1 ? '' : url.slice(hashAt + 1)
    const location = hashAt === -1 ? url : url.slice(0, hashAt)
    const queryAt = location.indexOf('?')
    const query = queryAt === -1 ? '' : location.slice(queryAt + 1)
    const base = queryAt === -1 ? location : location.slice(0, queryAt)

    let redacted = base.replace(USERINFO, '$1')
    if (query) {
        redacted += `?${redactParams(query)}`
    }
    if (fragment) {
        redacted += `#${isOpaqueFragment(fragment) ? REDACTED : redactParams(fragment)}`
    }
    return redactCredentialValues(redacted)
}
