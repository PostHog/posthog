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
        (route) =>
            ('match' in route && pathname === route.match) || ('prefix' in route && pathname.startsWith(route.prefix))
    )
}

export function buildRedirectUrl(authServer: string, pathname: string, search: string, route: AuthRedirect): string {
    const targetPath = route.rewriteTo ?? pathname
    return `${authServer}${targetPath}${search}`
}
