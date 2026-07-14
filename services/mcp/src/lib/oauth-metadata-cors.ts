/** PostHog app origins that render the OAuth consent page and fetch MCP metadata in-browser. */
export const OAUTH_CONSENT_PAGE_ORIGINS = [
    'https://us.posthog.com',
    'https://eu.posthog.com',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://localhost:8010',
    'http://127.0.0.1:8010',
    'http://localhost:8080',
    'http://127.0.0.1:8080',
] as const

export function corsHeadersForOAuthMetadata(request: Request): Record<string, string> {
    const origin = request.headers.get('Origin')
    if (!origin || !OAUTH_CONSENT_PAGE_ORIGINS.includes(origin as (typeof OAUTH_CONSENT_PAGE_ORIGINS)[number])) {
        return {}
    }
    return {
        'Access-Control-Allow-Origin': origin,
        'Access-Control-Allow-Methods': 'GET, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Max-Age': '3600',
        Vary: 'Origin',
    }
}

/** OPTIONS preflight for RFC 9728 metadata — shared by Hono and Cloudflare Workers. */
export function oauthMetadataPreflightResponse(request: Request): Response | null {
    if (request.method !== 'OPTIONS') {
        return null
    }
    const headers = corsHeadersForOAuthMetadata(request)
    return new Response(null, { status: 204, headers })
}
