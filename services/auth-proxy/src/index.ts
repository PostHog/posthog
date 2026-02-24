/**
 * auth.posthog.com — Cross-Region OAuth Proxy
 *
 * A Cloudflare Worker that sits in front of both US and EU PostHog instances,
 * providing a single OAuth endpoint that handles region routing transparently.
 *
 * Used by the PostHog MCP server, Twig, and any future OAuth integration
 * so they don't need separate US/EU URLs.
 */
import { handleAuthorize } from '@/handlers/authorize'
import { handleMetadata } from '@/handlers/metadata'
import { handleIntrospect, handleJwks, handleRevoke, handleUserInfo } from '@/handlers/passthrough'
import { handleRegister } from '@/handlers/register'
import { handleToken } from '@/handlers/token'

export interface Env {
    AUTH_KV: KVNamespace
}

export default {
    async fetch(request: Request, env: Env): Promise<Response> {
        const url = new URL(request.url)
        const path = url.pathname

        try {
            // Auth server metadata (RFC 8414)
            if (path === '/.well-known/oauth-authorization-server') {
                return handleMetadata(request)
            }

            // JWKS for token verification
            if (path === '/.well-known/jwks.json') {
                return handleJwks(request)
            }

            // Dynamic Client Registration (RFC 7591)
            if (
                (path === '/oauth/register/' || path === '/oauth/register' || path === '/register') &&
                request.method === 'POST'
            ) {
                return handleRegister(request, env.AUTH_KV)
            }

            // Authorization (shows region picker, then redirects)
            if (path === '/oauth/authorize/' || path === '/oauth/authorize' || path === '/authorize') {
                return handleAuthorize(request, env.AUTH_KV)
            }

            // Token exchange (proxy to correct region)
            if (
                (path === '/oauth/token/' || path === '/oauth/token' || path === '/token') &&
                request.method === 'POST'
            ) {
                return handleToken(request, env.AUTH_KV)
            }

            // Token revocation
            if ((path === '/oauth/revoke/' || path === '/oauth/revoke') && request.method === 'POST') {
                return handleRevoke(request, env.AUTH_KV)
            }

            // Token introspection
            if ((path === '/oauth/introspect/' || path === '/oauth/introspect') && request.method === 'POST') {
                return handleIntrospect(request)
            }

            // UserInfo
            if (path === '/oauth/userinfo/' || path === '/oauth/userinfo') {
                return handleUserInfo(request)
            }

            // Landing page
            if (path === '/') {
                return new Response('PostHog Auth Proxy — https://posthog.com/docs/model-context-protocol', {
                    headers: { 'Content-Type': 'text/plain' },
                })
            }

            return new Response('Not found', { status: 404 })
        } catch (error) {
            console.error('Unhandled error:', error instanceof Error ? error.message : error)
            return new Response(
                JSON.stringify({ error: 'server_error', error_description: 'An internal error occurred' }),
                {
                    status: 500,
                    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
                }
            )
        }
    },
}
