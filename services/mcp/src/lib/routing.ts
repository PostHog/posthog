// Authorization server redirect routes.
// MCP clients sometimes hit OAuth endpoints directly on this server instead of following
// the authorization server URLs from the protected resource metadata. Each entry defines
// a path pattern that should be redirected to the PostHog authorization server.

type RedirectStatus = 301 | 302
type AuthRedirect = { match: string; status: RedirectStatus } | { prefix: string; status: RedirectStatus }

const AUTH_SERVER_REDIRECTS: AuthRedirect[] = [
    // OAuth Authorization Server Metadata (RFC 8414) - clients fetch this directly
    // instead of using the authorization_servers field from protected resource metadata
    { match: '/.well-known/oauth-authorization-server', status: 302 },
    // JWKS endpoint for token verification
    { match: '/.well-known/jwks.json', status: 301 },
    // OAuth endpoints (authorize, token, register, revoke, introspect, userinfo)
    { prefix: '/oauth/', status: 301 },
]

export function matchAuthServerRedirect(pathname: string): AuthRedirect | undefined {
    return AUTH_SERVER_REDIRECTS.find(
        (route) =>
            ('match' in route && pathname === route.match) || ('prefix' in route && pathname.startsWith(route.prefix))
    )
}
