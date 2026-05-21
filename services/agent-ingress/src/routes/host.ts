import { Request } from 'ultimate-express'

/**
 * Pull the application host from the request, validating it against the configured
 * `.agents.posthog.com`-shaped suffix. Returns the full hostname (subdomain + suffix),
 * since the internal resolve endpoint matches on the full domain.
 */
export function extractHost(req: Request, domainSuffix: string): string | null {
    // Honor an explicit override header for clients that proxy us, but fall back to Host.
    const raw = (req.header('x-original-host') ?? req.hostname ?? '').toLowerCase().trim()
    if (!raw) {
        return null
    }
    if (!raw.endsWith(domainSuffix.toLowerCase())) {
        return null
    }
    return raw
}

/**
 * Path-based dispatch entry. When ingress is configured with
 * `ROUTING_MODE=path`, the URL carries the slug instead of the hostname:
 *
 *     /agents/<slug>/run
 *     /agents/<slug>/webhooks/slack
 *     /agents/<slug>/listen/<session_id>
 *     /agents/<slug>/send/<session_id>
 *     /agents/<slug>/cancel/<session_id>
 *
 * Useful for ngrok / cloudflared Quick Tunnels and other setups where you
 * can't get a wildcard subdomain. Returns the slug + the path the underlying
 * `route()` handler should see (the prefix stripped).
 *
 * Validates the slug shape conservatively so we don't accidentally treat
 * `..` / empty / arbitrary garbage as a tenant identifier.
 */
const PATH_PREFIX = '/agents/'
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/

export function extractSlugFromPath(path: string): { slug: string; remainder: string } | null {
    if (!path.startsWith(PATH_PREFIX)) {
        return null
    }
    const rest = path.slice(PATH_PREFIX.length)
    const sep = rest.indexOf('/')
    if (sep <= 0) {
        return null
    }
    const slug = rest.slice(0, sep).toLowerCase()
    if (!SLUG_PATTERN.test(slug)) {
        return null
    }
    const remainder = rest.slice(sep)
    return { slug, remainder }
}
