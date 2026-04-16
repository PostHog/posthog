/**
 * Input-validation helpers used at the trust boundary of the MCP server.
 *
 * The MCP server proxies untrusted input from MCP clients (and indirectly from
 * model-generated tool arguments) to PostHog's authenticated API. Any value
 * that ends up interpolated into a URL path, an outbound header, or an OAuth
 * Authorization header MUST be validated against an allowlist here so that an
 * attacker cannot:
 *
 *   - Smuggle path segments (e.g. `123/../../private`) into PostHog API URLs
 *     via a cached `projectId` / `orgId`.
 *   - Inject CR/LF or other control characters into outbound HTTP headers.
 *   - Spoof the `X-Forwarded-Host` header in production to redirect victims'
 *     OAuth metadata discovery to attacker-controlled hostnames.
 *
 * These checks intentionally err on the side of rejecting legitimate-looking
 * inputs that don't match the documented PostHog ID shapes; they are the
 * trust-boundary gate, not the place to be permissive.
 */

// PostHog project IDs are always integers (or the literal '@current'). We cap
// at 20 digits to keep the value safely below 64-bit integer range.
const PROJECT_ID_REGEX = /^(?:@current|[0-9]{1,20})$/

// PostHog organization IDs are UUIDs (or '@current'). We accept both upper-
// and lower-case hex.
const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const ORG_ID_REGEX = new RegExp(`^(?:@current|${UUID_REGEX.source.slice(1, -1)})$`, 'i')

// PostHog API tokens (`phx_…` personal keys, `pha_…` OAuth tokens) are URL-safe
// base64 / base32. We require the prefix and a strict charset cap to prevent
// header-smuggling payloads (CR/LF, NUL, `Bearer ` injection, etc.) from being
// echoed back into the outbound `Authorization` header.
const API_TOKEN_REGEX = /^(?:phx_|pha_)[A-Za-z0-9_-]{8,256}$/

// Cloud regions are always 'us' or 'eu' — anything else is hostile input.
const REGION_REGEX = /^(us|eu)$/i

// Hostnames we are willing to honor when echoed back via `X-Forwarded-Host`.
// Production must never trust an arbitrary forwarded host because the value
// flows into the OAuth `WWW-Authenticate` `resource_metadata` URL that MCP
// clients fetch to discover the authorization server.
const TRUSTED_PROXY_HOSTS = new Set(['mcp.posthog.com', 'mcp-eu.posthog.com'])

// Hostnames where reverse-proxy-style header overrides are safe to honor (local
// dev with ngrok / cloudflared etc.). Production hostnames are matched via
// `TRUSTED_PROXY_HOSTS`.
const LOCAL_DEV_HOSTS = new Set(['localhost', '127.0.0.1', '0.0.0.0', '[::1]'])

// Forwarded hosts must look like a hostname (optionally with a port) — never
// contain whitespace, control chars, or path/query separators.
const HOSTNAME_REGEX = /^[A-Za-z0-9.\-_]+(?::\d{1,5})?$/

export function isValidProjectId(value: unknown): value is string {
    return typeof value === 'string' && PROJECT_ID_REGEX.test(value)
}

export function isValidOrganizationId(value: unknown): value is string {
    return typeof value === 'string' && ORG_ID_REGEX.test(value)
}

export function isValidApiToken(value: unknown): value is string {
    return typeof value === 'string' && API_TOKEN_REGEX.test(value)
}

export function isValidRegion(value: unknown): value is string {
    return typeof value === 'string' && REGION_REGEX.test(value)
}

export function isValidHostname(value: unknown): value is string {
    return typeof value === 'string' && HOSTNAME_REGEX.test(value)
}

/**
 * Decide whether a `X-Forwarded-Host` value coming in on `requestHostname`
 * should be honored. We honor it only when:
 *
 *   - The forwarded value is a syntactically valid hostname, AND
 *   - The actual request hostname is a known trusted proxy (production), OR
 *   - The actual request hostname is local dev (where MCP devs commonly tunnel
 *     via ngrok/cloudflared and need the forwarded host to build OAuth URLs).
 */
export function shouldHonorForwardedHost(forwardedHost: string, requestHostname: string): boolean {
    if (!isValidHostname(forwardedHost)) {
        return false
    }

    const normalizedRequest = requestHostname.toLowerCase()
    if (TRUSTED_PROXY_HOSTS.has(normalizedRequest) || LOCAL_DEV_HOSTS.has(normalizedRequest)) {
        return true
    }

    return false
}

/**
 * Encode a validated PostHog ID for safe interpolation into URL paths. The
 * value is required to have already passed `isValidProjectId` /
 * `isValidOrganizationId`; this is defense-in-depth in case a future caller
 * forgets to validate.
 */
export function encodePostHogIdForPath(value: string): string {
    return encodeURIComponent(value)
}

const SECRET_PATTERNS: Array<{ pattern: RegExp; replacement: string }> = [
    // Bearer tokens in URLs or strings (`Bearer phx_abc…` / `Bearer pha_abc…`).
    { pattern: /Bearer\s+(?:phx_|pha_)[A-Za-z0-9_-]+/gi, replacement: 'Bearer [REDACTED]' },
    // Bare PostHog tokens that happen to land in error messages.
    { pattern: /\b(?:phx_|pha_)[A-Za-z0-9_-]{8,}/g, replacement: '[REDACTED_TOKEN]' },
    // Inkeep / generic "sk_…" or "Bearer sk_…" style upstream API keys.
    { pattern: /\b(?:sk|key|api[_-]?key)_[A-Za-z0-9_-]{16,}/gi, replacement: '[REDACTED_KEY]' },
]

/**
 * Strip secret-looking material from log messages before they leave the worker.
 * Used by error-handling paths so that an upstream 401/500 body that happens to
 * echo the inbound bearer token doesn't get persisted in observability storage.
 */
export function redactSecrets(message: string): string {
    let out = message
    for (const { pattern, replacement } of SECRET_PATTERNS) {
        out = out.replace(pattern, replacement)
    }
    return out
}
