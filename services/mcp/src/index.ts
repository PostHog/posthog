import { getPostHogClient } from '@/lib/analytics'
import { MCP_DOCS_URL, OAUTH_SCOPES_SUPPORTED, getAuthorizationServerUrl } from '@/lib/constants'
import {
    buildInsufficientScopeChallenge,
    ErrorCode,
    findPostHogPermissionError,
    formatPermissionErrorMessage,
} from '@/lib/errors'
import { RequestLogger, withLogging } from '@/lib/logging'
import { extractClientInfoFromBody } from '@/lib/mcp-client-info'
import { buildRedirectUrl, matchAuthServerRedirect } from '@/lib/routing'
import { hash, parseMcpMode, sanitizeHeaderValue } from '@/lib/utils'
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

// Detect region from hostname (mcp-eu.posthog.com) or query param (?region=eu)
// Hostname takes precedence as it's the workaround for Claude Code's OAuth bug
function getRegionFromRequest(request: Request): CloudRegion | null {
    const hostnameRegion = getRegionFromHostname(request)
    if (hostnameRegion) {
        return hostnameRegion
    }

    const url = new URL(request.url)
    const queryRegion = url.searchParams.get('region') as CloudRegion | null
    return queryRegion
}

// Detect error codes and return appropriate responses
const onThenErrorHandler = async (response: Response): Promise<Response> => {
    if (!response.ok) {
        const body = await response.clone().text()
        const errorResponse = generateErrorResponseFromMessage(body)
        if (errorResponse) {
            return errorResponse
        }
    }

    return response
}

const onCatchErrorHandler = async (
    error: Error,
    log: RequestLogger,
    ctx: ExecutionContext<RequestProperties>
): Promise<Response> => {
    const permissionError = findPostHogPermissionError(error)
    if (permissionError) {
        return new Response(formatPermissionErrorMessage(permissionError), {
            status: 403,
            headers: {
                'Content-Type': 'text/plain; charset=utf-8',
                'WWW-Authenticate': buildInsufficientScopeChallenge(permissionError),
            },
        })
    }

    const knownErrorResponse = generateErrorResponseFromMessage(error.message)
    if (knownErrorResponse) {
        return knownErrorResponse
    }

    // Unrecognized error → opaque 500 to the client. Surface the underlying
    // error in the wide log and PostHog so we can debug without scraping CF
    // request traces.
    log.extend({
        errorName: error?.name,
        errorMessage: error?.message,
        errorStack: error?.stack,
    })

    try {
        const client = getPostHogClient()
        const distinctId = ctx.props?.userHash
        client.captureException(error, distinctId, {
            team: 'posthog_ai',
            source: 'mcp_request_handler',
            mcp_transport: ctx.props?.transport,
            mcp_version: ctx.props?.version,
            has_organization_id: !!ctx.props?.organizationId,
            has_project_id: !!ctx.props?.projectId,
        })
        ctx.waitUntil(client.flush())
    } catch {
        // Never let observability break the request.
    }

    return new Response('Internal server error', { status: 500 })
}

const generateErrorResponseFromMessage = (message: string): Response | null => {
    if (message.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
        return new Response('OAuth token is inactive', { status: 401 })
    } else if (message.includes(ErrorCode.INVALID_API_KEY)) {
        return new Response('Invalid API key', { status: 401 })
    }

    return null
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

    // OpenAI ChatGPT App Directory domain verification
    if (url.pathname === '/.well-known/openai-apps-challenge') {
        return new Response('pRLV9JYbPOF5Dy039v3Rn3-qrMuKqZ2_4SsX9GoL9aU', {
            headers: { 'content-type': 'text/plain' },
        })
    }

    // Health endpoint for uptime probes and load-balancer checks.
    // Public and unauthenticated so external monitors can hit it without a token.
    if (url.pathname === '/health' || url.pathname === '/healthz') {
        return new Response(JSON.stringify({ status: 'ok' }), {
            headers: {
                'Content-Type': 'application/json',
                'Cache-Control': 'no-store',
            },
        })
    }

    // Detect region from hostname (mcp-eu.posthog.com) or query param (?region=eu)
    // Hostname takes precedence as it's the workaround for Claude Code's OAuth bug
    const effectiveRegion = getRegionFromRequest(request)
    log.extend({ region: effectiveRegion })

    // Authorization server redirects
    //
    // MCP clients sometimes hit OAuth endpoints directly on this server instead of
    // following URLs from the authorization server metadata. We redirect these to
    // the correct PostHog authorization server for the user's region.
    // See: https://github.com/anthropics/claude-code/issues/2267
    const redirect = matchAuthServerRedirect(url.pathname)
    if (redirect) {
        const authServer = getAuthorizationServerUrl()
        const redirectTo = buildRedirectUrl(authServer, url.pathname, url.search, redirect)

        log.extend({ redirectTo })
        return Response.redirect(redirectTo, redirect.status)
    }

    // The legacy SSE transport (`/sse`) is deprecated in favor of `/mcp`
    // (Streamable HTTP). Permanently redirect `/sse*` to the equivalent `/mcp*`.
    // We tag the redirect Location with `_deprecated=sse` so the followup
    // request on /mcp carries the marker — that lets us correlate
    // success/failure on /mcp back to clients that came in via the deprecated
    // path, even after the protocol-level handoff.
    if (url.pathname === '/sse' || url.pathname.startsWith('/sse/')) {
        const target = getPublicUrl(request)
        target.pathname = '/mcp' + url.pathname.slice('/sse'.length)
        target.searchParams.set('_deprecated', 'sse')
        log.extend({ deprecation: 'sse', redirectTo: target.toString() })
        return Response.redirect(target.toString(), 308)
    }

    // OAuth Protected Resource Metadata (RFC 9728)
    // This endpoint tells MCP clients where to authenticate to get tokens.
    //
    // Per RFC 9728, the well-known URL is constructed by inserting /.well-known/oauth-protected-resource
    // between the host and the path. For example:
    // - Resource: https://mcp.posthog.com/mcp → Well-known: https://mcp.posthog.com/.well-known/oauth-protected-resource/mcp
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

        // Determine authorization server for OAuth.
        // POSTHOG_API_BASE_URL takes precedence for self-hosted, otherwise routes to oauth.posthog.com.
        const authorizationServer = getAuthorizationServerUrl()

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

    // Organization and project IDs can be provided via headers or query params.
    // When set, they pin the MCP session to a specific org/project and remove the switch tools.
    const organizationId =
        request.headers.get('x-posthog-organization-id') || url.searchParams.get('organization_id') || undefined
    const projectId = request.headers.get('x-posthog-project-id') || url.searchParams.get('project_id') || undefined

    const rawUserAgent = request.headers.get('User-Agent') || undefined
    const clientUserAgent = sanitizeHeaderValue(rawUserAgent)

    // Self-identification signal set by a wrapping consumer app (e.g. PostHog's
    // Tasks sandbox, or an AI-tool plugin that auto-installs the MCP) when the
    // wrapped MCP client's name is too generic to distinguish (e.g. both direct
    // and sandboxed Claude Code send `claude-code`). Query-param fallback for
    // clients that only let the user customize the URL, not headers.
    const mcpConsumer = sanitizeHeaderValue(
        request.headers.get('x-posthog-mcp-consumer') || url.searchParams.get('consumer') || undefined
    )

    // Extract MCP `clientInfo` eagerly from the JSON-RPC initialize message in the
    // request body (streamable-http only). The framework's async
    // `getInitializeRequest()` relies on Durable Object storage which is only
    // written after `onStart`/`init()` runs, so on the first connect `init()` has
    // no client info to read. Parsing the body here gives `init()` the values
    // synchronously via `RequestProperties`.
    const clientInfo = await extractClientInfoFromBody(request)

    Object.assign(ctx.props, {
        apiToken: token,
        userHash: hash(token),
        sessionId: sessionId || undefined,
        organizationId,
        projectId,
        clientUserAgent,
        mcpConsumer,
        mcpClientName: clientInfo.clientName,
        mcpClientVersion: clientInfo.clientVersion,
        mcpProtocolVersion: clientInfo.protocolVersion,
        requestStartTime: Date.now(),
    })

    // Search params are used to build up the list of available tools. If no features are provided, all tools are available.
    // If features are provided, only tools matching those features will be available.
    // Features are provided as a comma-separated list in the "features" query parameter.
    // Example: ?features=org,insights
    const featuresParam = url.searchParams.get('features')
    const features = featuresParam ? featuresParam.split(',').filter(Boolean) : undefined

    const toolsParam = url.searchParams.get('tools')
    const tools = toolsParam ? toolsParam.split(',').filter(Boolean) : undefined

    // Region param is used to route API calls to the correct PostHog instance (US or EU).
    // This is set by the wizard based on user's cloud region selection during MCP setup.
    const regionParam = url.searchParams.get('region') || undefined

    const version = Number(request.headers.get('x-posthog-mcp-version') || url.searchParams.get('v')) || 1

    const readOnlyRaw = request.headers.get('x-posthog-readonly') || url.searchParams.get('readonly')
    const readOnly = readOnlyRaw === 'true' || readOnlyRaw === '1' || undefined

    // Explicit selection between tool-based and CLI-based MCP. Falls back to the
    // flag + client-detection logic in `MCP.init()` when unset. See `parseMcpMode`.
    const mode = parseMcpMode(request.headers.get('x-posthog-mcp-mode') || url.searchParams.get('mode'))

    const extraContextProps = { features, tools, region: regionParam, version, readOnly, mode }
    Object.assign(ctx.props, extraContextProps)
    log.extend(extraContextProps)
    if (mcpConsumer) {
        log.extend({ mcpConsumer })
    }
    if (clientInfo.clientName) {
        log.extend({ mcpClientName: clientInfo.clientName })
    }

    // Marker set by the /sse → /mcp redirect handler above. Lets us correlate
    // success/failure on this /mcp request back to clients that originated on
    // the deprecated /sse path — both in worker logs and in the `mcp init`
    // analytics event (via `RequestProperties.viaSseRedirect`).
    const viaSseRedirect = url.searchParams.get('_deprecated') === 'sse'
    if (viaSseRedirect) {
        log.extend({ via: 'sse_redirect' })
        Object.assign(ctx.props, { viaSseRedirect: true })
    }

    let server: Promise<Response> | null = null
    if (url.pathname.startsWith('/mcp')) {
        Object.assign(ctx.props, { transport: 'streamable-http' })
        server = MCP.serve('/mcp').fetch(request, env, ctx)
    }

    if (server !== null) {
        return server.then(onThenErrorHandler).catch((error: Error) => onCatchErrorHandler(error, log, ctx))
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
