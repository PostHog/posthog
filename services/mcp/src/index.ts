import { MCP_DOCS_URL, OAUTH_SCOPES_SUPPORTED, getAuthorizationServerUrl } from '@/lib/constants'
import { ErrorCode } from '@/lib/errors'
import { RequestLogger, withLogging } from '@/lib/logging'
import { hash } from '@/lib/utils'
import type { CloudRegion } from '@/tools/types'

import { MCP, RequestProperties } from './mcp'
import RAW_LANDING_HTML from './static/landing.html'

const PARSED_LANDING_HTML = RAW_LANDING_HTML.replace('{{DOCS_URL}}', MCP_DOCS_URL)

// Helper to get the public-facing URL, respecting reverse proxy headers
// This is needed for local development with ngrok/cloudflared where request.url
// shows http://localhost but the actual URL is https://...ngrok-free.dev
function getPublicUrl(request: Request): URL {
    const url = new URL(request.url)

    // Check for X-Forwarded-Host (ngrok, cloudflared, and most reverse proxies)
    const forwardedHost = request.headers.get('X-Forwarded-Host')
    if (forwardedHost) {
        url.host = forwardedHost
    }

    // Check for X-Forwarded-Proto (https vs http)
    const forwardedProto = request.headers.get('X-Forwarded-Proto')
    if (forwardedProto) {
        url.protocol = forwardedProto + ':'
    }

    return url
}

// Detect region from hostname for EU subdomain routing.
// This is a workaround for Claude Code's OAuth bug where it ignores the
// authorization_servers field from OAuth protected resource metadata and
// instead fetches /.well-known/oauth-authorization-server directly from the MCP server.
// See: https://github.com/anthropics/claude-code/issues/2267
//
// By using a separate subdomain (mcp-eu.posthog.com), Claude Code's request to
// /.well-known/oauth-authorization-server will hit our server with the EU hostname,
// allowing us to redirect to the correct EU OAuth server.
function getRegionFromHostname(request: Request): CloudRegion | undefined {
    const publicUrl = getPublicUrl(request)
    // DNS hostnames are case-insensitive, so normalize to lowercase
    if (publicUrl.hostname.toLowerCase() === 'mcp-eu.posthog.com') {
        return 'eu'
    }
    return undefined
}

// Detect error codes and return appropriate responses
const errorHandler = async (response: Response): Promise<Response> => {
    if (!response.ok) {
        const body = await response.clone().text()
        if (body.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
            return new Response('OAuth token is inactive', { status: 401 })
        }
    }

    return response
}

const handleRequest = async (
    request: Request,
    env: Env,
    ctx: ExecutionContext<RequestProperties>,
    log: RequestLogger
): Promise<Response> => {
    const url = new URL(request.url)
    log.extend({ route: url.pathname })

    if (url.pathname === '/') {
        return new Response(PARSED_LANDING_HTML, {
            headers: { 'content-type': 'text/html; charset=utf-8' },
        })
    }

    // Detect region from hostname (mcp-eu.posthog.com) or query param (?region=eu)
    // Hostname takes precedence as it's the workaround for Claude Code's OAuth bug
    const hostnameRegion = getRegionFromHostname(request)
    const queryRegion = url.searchParams.get('region')
    const effectiveRegion = hostnameRegion || queryRegion
    log.extend({ region: effectiveRegion })

    // OAuth Authorization Server Metadata (RFC 8414)
    // Claude Code fetches this endpoint directly from the MCP server URL instead of
    // following the authorization_servers from the protected resource metadata.
    // See: https://github.com/anthropics/claude-code/issues/2267
    //
    // We redirect to the correct PostHog region's OAuth metadata endpoint.
    if (url.pathname === '/.well-known/oauth-authorization-server') {
        const authServer = getAuthorizationServerUrl(effectiveRegion)
        const redirectTo = `${authServer}/.well-known/oauth-authorization-server`

        log.extend({ redirectTo })
        return Response.redirect(redirectTo, 302)
    }

    // OAuth Protected Resource Metadata (RFC 9728)
    // This endpoint tells MCP clients where to authenticate to get tokens.
    //
    // Per RFC 9728, the well-known URL is constructed by inserting /.well-known/oauth-protected-resource
    // between the host and the path. For example:
    // - Resource: https://mcp.posthog.com/mcp → Well-known: https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp
    // - Resource: https://mcp.posthog.com/sse → Well-known: https://mcp.posthog.com/.well-known/oauth-protected-resource/sse
    //
    // OAuth flow for MCP:
    // 1. Client connects to MCP server without a token
    // 2. MCP returns 401 with WWW-Authenticate header pointing to this metadata endpoint
    // 3. Client fetches this metadata to discover the authorization server
    // 4. Client performs OAuth flow with PostHog (US or EU based on region param)
    // 5. Client reconnects to MCP with the access token
    const wellKnownPrefix = '/.well-known/oauth-protected-resource'
    if (url.pathname.startsWith(wellKnownPrefix)) {
        // Extract the resource path from after the well-known prefix
        // e.g., /.well-known/oauth-protected-resource/mcp → /mcp
        const resourcePath = url.pathname.slice(wellKnownPrefix.length) || '/'
        const resourceUrl = getPublicUrl(request)
        resourceUrl.pathname = resourcePath
        resourceUrl.search = ''

        // Determine authorization server based on hostname or region param.
        // POSTHOG_API_BASE_URL takes precedence for self-hosted, otherwise routes to US/EU.
        const authorizationServer = getAuthorizationServerUrl(effectiveRegion)

        return new Response(
            JSON.stringify({
                resource: resourceUrl.toString().replace(/\/$/, ''),
                authorization_servers: [authorizationServer],
                scopes_supported: OAUTH_SCOPES_SUPPORTED,
                bearer_methods_supported: ['header'],
            }),
            {
                headers: {
                    'Content-Type': 'application/json',
                    'Cache-Control': 'public, max-age=3600',
                },
            }
        )
    }

    const token = request.headers.get('Authorization')?.split(' ')[1]
    const sessionId = url.searchParams.get('sessionId')

    if (!token) {
        // Return 401 with WWW-Authenticate header per RFC 9728.
        // The resource_metadata URL tells OAuth-capable clients where to discover auth server.
        // Per RFC 9728, the well-known URL is constructed by inserting the well-known path
        // between the host and the resource path:
        // - Resource /mcp → metadata at /.well-known/oauth-protected-resource/mcp
        // - Resource /sse → metadata at /.well-known/oauth-protected-resource/sse
        const metadataUrl = getPublicUrl(request)
        metadataUrl.pathname = `/.well-known/oauth-protected-resource${url.pathname}`
        metadataUrl.search = ''
        if (effectiveRegion) {
            metadataUrl.searchParams.set('region', effectiveRegion)
        }

        log.extend({ authError: 'no_token' })
        return new Response(
            `No token provided, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
            {
                status: 401,
                headers: { 'WWW-Authenticate': `Bearer resource_metadata="${metadataUrl.toString()}"` },
            }
        )
    }

    if (!token.startsWith('phx_') && !token.startsWith('pha_')) {
        log.extend({ authError: 'invalid_token_format' })
        return new Response(
            `Invalid token, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
            { status: 401 }
        )
    }

    Object.assign(ctx.props, {
        apiToken: token,
        userHash: hash(token),
        sessionId: sessionId || undefined,
    })

    // Search params are used to build up the list of available tools. If no features are provided, all tools are available.
    // If features are provided, only tools matching those features will be available.
    // Features are provided as a comma-separated list in the "features" query parameter.
    // Example: ?features=org,insights
    const featuresParam = url.searchParams.get('features')
    const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined

    // Region param is used to route API calls to the correct PostHog instance (US or EU).
    // This is set by the wizard based on user's cloud region selection during MCP setup.
    const regionParam = url.searchParams.get('region') || undefined

    Object.assign(ctx.props, { features, region: regionParam })
    log.extend({ features })

    if (url.pathname.startsWith('/mcp')) {
        return MCP.serve('/mcp').fetch(request, env, ctx).then(errorHandler)
    }

    if (url.pathname.startsWith('/sse')) {
        return MCP.serveSSE('/sse').fetch(request, env, ctx).then(errorHandler)
    }

    log.extend({ error: 'route_not_found' })
    return new Response('Not found', { status: 404 })
}

// Durable Object class export - required for Wrangler to find the class for the MCP_OBJECT binding
export { MCP } from './mcp'

// Worker entry point
export default {
    fetch: withLogging(handleRequest),
}
