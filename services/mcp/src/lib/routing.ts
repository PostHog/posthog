import type { CloudRegion } from '@/tools/types'

// Resolve the public-facing URL for a request, honoring reverse-proxy headers.
// Needed for local dev with ngrok/cloudflared, and for k8s deployments behind an ingress
// where `request.url` is the in-cluster URL but the well-known/RFC-9728 metadata must
// advertise the externally reachable origin.
export function getPublicUrl(request: Request): URL {
    const url = new URL(request.url)

    const forwardedHost = request.headers.get('X-Forwarded-Host')
    if (forwardedHost) {
        url.host = forwardedHost
    }

    const forwardedProto = request.headers.get('X-Forwarded-Proto')
    if (forwardedProto) {
        url.protocol = forwardedProto + ':'
    }

    return url
}

// Detect region from the request hostname.
// This is a workaround for Claude Code's OAuth bug where it ignores the
// authorization_servers field from RFC 9728 metadata and instead fetches
// /.well-known/oauth-authorization-server directly from the MCP server.
// See: https://github.com/anthropics/claude-code/issues/2267
//
// By using a region-pinned subdomain, we can route the OAuth fallback to the
// correct PostHog authorization server.
export function getRegionFromHostname(request: Request): CloudRegion | undefined {
    const hostname = getPublicUrl(request).hostname.toLowerCase()
    if (hostname === 'mcp-eu.posthog.com' || hostname === 'mcp.eu.posthog.com') {
        return 'eu'
    }
    if (hostname === 'mcp.us.posthog.com') {
        return 'us'
    }
    return undefined
}

// Detect region from hostname (region-pinned subdomain) or `?region=` query param.
// Hostname takes precedence — it's the workaround for Claude Code's OAuth bug.
export function getRegionFromRequest(request: Request): CloudRegion | null {
    const hostnameRegion = getRegionFromHostname(request)
    if (hostnameRegion) {
        return hostnameRegion
    }

    const url = new URL(request.url)
    return url.searchParams.get('region') as CloudRegion | null
}

// Authorization server redirect routes.
// MCP clients sometimes hit OAuth endpoints directly on this server instead of following
// the authorization server URLs from the protected resource metadata. Each entry defines
// a path pattern that should be redirected to the PostHog authorization server.

type RedirectStatus = 301 | 302 | 307
type AuthRedirect = {
    status: RedirectStatus
    // Optional path rewrite: if set, replaces the matched path in the redirect URL.
    // Used when the MCP spec fallback paths (e.g. /register) differ from the
    // PostHog backend paths (e.g. /oauth/register).
    rewriteTo?: string
} & ({ match: string } | { prefix: string })

const AUTH_SERVER_REDIRECTS: AuthRedirect[] = [
    // OAuth Authorization Server Metadata (RFC 8414) - clients fetch this directly
    // instead of using the authorization_servers field from protected resource metadata
    { match: '/.well-known/oauth-authorization-server', status: 302 },
    // JWKS endpoint for token verification
    { match: '/.well-known/jwks.json', status: 301 },
    // OAuth endpoints (authorize, token, register, revoke, introspect, userinfo)
    { prefix: '/oauth/', status: 301 },
    // MCP 3/26 spec fallback endpoints - clients hit these directly when the authorization
    // server metadata is not available. PostHog serves these under /oauth/ so we rewrite.
    // /register and /token use 307 to preserve POST method and body across the redirect.
    // /authorize uses 302 as it's a GET request.
    { match: '/register', status: 307, rewriteTo: '/oauth/register' },
    { match: '/authorize', status: 302, rewriteTo: '/oauth/authorize' },
    { match: '/token', status: 307, rewriteTo: '/oauth/token' },
]

export function matchAuthServerRedirect(pathname: string): AuthRedirect | undefined {
    return AUTH_SERVER_REDIRECTS.find(
        (redirect) =>
            ('match' in redirect && pathname === redirect.match) ||
            ('prefix' in redirect && pathname.startsWith(redirect.prefix))
    )
}

export function buildRedirectUrl(authServer: string, pathname: string, search: string, route: AuthRedirect): string {
    const targetPath = route.rewriteTo ?? pathname
    return `${authServer}${targetPath}${search}`
}
