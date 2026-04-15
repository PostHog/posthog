/**
 * oauth.posthog.com — Cross-Region OAuth Proxy
 *
 * A Cloudflare Worker that sits in front of both US and EU PostHog instances,
 * providing a single OAuth endpoint that handles region routing transparently.
 *
 * Used by the PostHog MCP server, PostHog Code, and any future OAuth integration
 * so they don't need separate US/EU URLs.
 */
import { handleAuthorize } from '@/handlers/authorize'
import { handleCallback } from '@/handlers/callback'
import { handleMetadata } from '@/handlers/metadata'
import { handleIntrospect, handleJwks, handleRevoke, handleUserInfo } from '@/handlers/passthrough'
import { handleRegister } from '@/handlers/register'
import { handleToken } from '@/handlers/token'

export interface Env {
    AUTH_KV: KVNamespace
}

type Handler = (request: Request, kv: KVNamespace) => Response | Promise<Response>

interface Route {
    paths: string[]
    method?: string
    handler: Handler
}

function normalizePath(path: string): string {
    return path.endsWith('/') ? path.slice(0, -1) : path
}

const routes: Route[] = [
    {
        paths: ['/.well-known/oauth-authorization-server'],
        handler: handleMetadata,
    },
    {
        paths: ['/.well-known/jwks.json'],
        handler: handleJwks,
    },
    {
        paths: ['/oauth/register', '/register'],
        method: 'POST',
        handler: handleRegister,
    },
    {
        paths: ['/oauth/authorize', '/authorize'],
        handler: handleAuthorize,
    },
    {
        paths: ['/oauth/callback'],
        handler: handleCallback,
    },
    {
        paths: ['/oauth/token', '/token'],
        method: 'POST',
        handler: handleToken,
    },
    {
        paths: ['/oauth/revoke'],
        method: 'POST',
        handler: handleRevoke,
    },
    {
        paths: ['/oauth/introspect'],
        method: 'POST',
        handler: handleIntrospect,
    },
    {
        paths: ['/oauth/userinfo'],
        handler: handleUserInfo,
    },
]

export default {
    async fetch(request: Request, env: Env): Promise<Response> {
        const url = new URL(request.url)
        const normalized = normalizePath(url.pathname)

        try {
            for (const route of routes) {
                if (route.method && request.method !== route.method) {
                    continue
                }
                if (route.paths.some((p) => normalizePath(p) === normalized)) {
                    return route.handler(request, env.AUTH_KV)
                }
            }

            if (normalized === '') {
                return new Response('PostHog OAuth Proxy — https://posthog.com/docs/model-context-protocol', {
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
