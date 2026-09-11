import { POSTHOG_US_BASE_URL, proxyOrigin } from '@/lib/constants'

/**
 * Discovery documents, fetched from the authoritative source (us.posthog.com) and rewritten so
 * every endpoint they name points at this proxy. Both are built in posthog/api/oauth/metadata.py.
 */

const CACHE_TTL_MS = 600 * 1000

const MANIFEST_PATH = '/auth.md'

// `posthog_base_url` names the region a token came from rather than an endpoint to call, so it
// keeps its regional value while every other regional URL is rewritten.
const REGIONAL_VALUE_FIELDS = ['posthog_base_url']

type Metadata = Record<string, unknown>

interface CachedDocument {
    body: string
    cachedUntil: number
}

const cache = new Map<string, CachedDocument>()

async function fetchAuthoritativeMetadata(path: string): Promise<Metadata> {
    const response = await fetch(`${POSTHOG_US_BASE_URL}${path}`)
    if (!response.ok) {
        throw new Error(`Failed to fetch ${path}: ${response.statusText}`)
    }

    return response.json() as Promise<Metadata>
}

/**
 * A rule rather than a field list, so an endpoint added to posthog/api/oauth/metadata.py is
 * rewritten here without a matching change.
 */
function rewriteEndpoints(value: unknown, origin: string): unknown {
    if (typeof value === 'string') {
        return value.startsWith(POSTHOG_US_BASE_URL) ? `${origin}${value.slice(POSTHOG_US_BASE_URL.length)}` : value
    }

    if (Array.isArray(value)) {
        return value.map((item) => rewriteEndpoints(item, origin))
    }

    if (value && typeof value === 'object') {
        return Object.fromEntries(
            Object.entries(value as Metadata).map(([field, nested]) => [
                field,
                REGIONAL_VALUE_FIELDS.includes(field) ? nested : rewriteEndpoints(nested, origin),
            ])
        )
    }

    return value
}

async function serveDocument(request: Request, path: string): Promise<Response> {
    const origin = proxyOrigin(request)
    const cacheKey = `${path}|${origin}`
    const cached = cache.get(cacheKey)

    if (!cached || cached.cachedUntil <= Date.now()) {
        try {
            const metadata = await fetchAuthoritativeMetadata(path)
            const body = JSON.stringify(rewriteEndpoints(metadata, origin))
            cache.set(cacheKey, { body, cachedUntil: Date.now() + CACHE_TTL_MS })
        } catch (error) {
            console.error(
                JSON.stringify({
                    handler: 'metadata',
                    path,
                    error: error instanceof Error ? error.message : 'unknown error',
                })
            )
            return new Response(
                JSON.stringify({
                    error: 'server_error',
                    error_description: 'Unable to fetch authorization server metadata',
                }),
                { status: 502, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
            )
        }
    }

    return new Response(cache.get(cacheKey)!.body, {
        headers: {
            'Content-Type': 'application/json',
            'Cache-Control': 'public, max-age=3600',
            'Access-Control-Allow-Origin': '*',
        },
    })
}

export async function handleMetadata(request: Request): Promise<Response> {
    return serveDocument(request, '/.well-known/oauth-authorization-server')
}

export async function handleOpenIdConfiguration(request: Request): Promise<Response> {
    return serveDocument(request, '/.well-known/openid-configuration')
}

/**
 * The auth.md agent manifest, which the authorization server metadata points at through
 * `agent_auth.skill`. Markdown rather than JSON, so the rewrite is a plain substitution: every URL
 * in the document is built from the serving instance's base URL.
 */
export async function handleClientManifest(request: Request): Promise<Response> {
    const origin = proxyOrigin(request)
    const cacheKey = `${MANIFEST_PATH}|${origin}`
    const cached = cache.get(cacheKey)

    if (!cached || cached.cachedUntil <= Date.now()) {
        try {
            const response = await fetch(`${POSTHOG_US_BASE_URL}${MANIFEST_PATH}`)
            if (!response.ok) {
                throw new Error(`Failed to fetch ${MANIFEST_PATH}: ${response.statusText}`)
            }

            const body = (await response.text()).split(POSTHOG_US_BASE_URL).join(origin)
            cache.set(cacheKey, { body, cachedUntil: Date.now() + CACHE_TTL_MS })
        } catch (error) {
            console.error(
                JSON.stringify({
                    handler: 'manifest',
                    error: error instanceof Error ? error.message : 'unknown error',
                })
            )
            return new Response('Unable to fetch the client manifest', { status: 502 })
        }
    }

    return new Response(cache.get(cacheKey)!.body, {
        headers: {
            'Content-Type': 'text/markdown; charset=utf-8',
            'Cache-Control': 'public, max-age=3600',
            'Access-Control-Allow-Origin': '*',
        },
    })
}
