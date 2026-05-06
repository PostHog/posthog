import { getPostHogClient } from '@/lib/analytics'
import {
    buildInvalidTokenFormatResponse,
    buildMissingTokenResponse,
    mapErrorToAuthResponse,
    mapKnownErrorMessage,
} from '@/lib/auth-errors'
import { MCP_DOCS_URL, OAUTH_SCOPES_SUPPORTED, getAuthorizationServerUrl } from '@/lib/constants'
import { RequestLogger, withLogging } from '@/lib/logging'
import { extractClientInfoFromBody } from '@/lib/mcp-client-info'
import { parseRequestProperties } from '@/lib/request-properties'
import { buildRedirectUrl, getPublicUrl, getRegionFromRequest, matchAuthServerRedirect } from '@/lib/routing'

import { MCP, RequestProperties } from './mcp'

const onThenErrorHandler = async (response: Response): Promise<Response> => {
    if (!response.ok) {
        const body = await response.clone().text()
        const errorResponse = mapKnownErrorMessage(body)
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
    const authResponse = mapErrorToAuthResponse(error)
    if (authResponse) {
        return authResponse
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

const handleRequest = async (
    request: Request,
    env: Env,
    ctx: ExecutionContext<RequestProperties>,
    log: RequestLogger
): Promise<Response> => {
    const url = new URL(request.url)
    log.extend({ route: url.pathname })

    if (url.pathname === '/') {
        return Response.redirect(MCP_DOCS_URL, 302)
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

    const effectiveRegion = getRegionFromRequest(request)
    log.extend({ region: effectiveRegion })

    // Authorization server redirects: MCP clients sometimes hit OAuth endpoints
    // directly instead of following URLs from the authorization server metadata.
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

    // OAuth Protected Resource Metadata (RFC 9728).
    // Per RFC 9728, the well-known URL is constructed by inserting
    // /.well-known/oauth-protected-resource between host and resource path.
    const wellKnownPrefix = '/.well-known/oauth-protected-resource'
    if (url.pathname.startsWith(wellKnownPrefix)) {
        const resourcePath = url.pathname.slice(wellKnownPrefix.length) || '/'
        const resourceUrl = getPublicUrl(request)
        resourceUrl.pathname = resourcePath
        resourceUrl.search = ''

        return new Response(
            JSON.stringify({
                resource: resourceUrl.toString().replace(/\/$/, ''),
                authorization_servers: [getAuthorizationServerUrl()],
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

    if (!token) {
        log.extend({ authError: 'no_token' })
        return buildMissingTokenResponse(request, effectiveRegion)
    }

    if (!token.startsWith('phx_') && !token.startsWith('pha_')) {
        log.extend({ authError: 'invalid_token_format' })
        return buildInvalidTokenFormatResponse()
    }

    // Extract MCP `clientInfo` eagerly from the JSON-RPC initialize message in the
    // request body (streamable-http only). The framework's async
    // `getInitializeRequest()` relies on Durable Object storage which is only
    // written after `onStart`/`init()` runs, so on the first connect `init()` has
    // no client info to read. Parsing the body here gives `init()` the values
    // synchronously via `RequestProperties`.
    const clientInfo = await extractClientInfoFromBody(request)

    // /sse → /mcp redirect handler above is the only path SSE clients take;
    // arrival here means streamable-http (or an unknown path that 404s below).
    const transport: RequestProperties['transport'] = url.pathname.startsWith('/mcp')
        ? 'streamable-http'
        : undefined
    let server: Promise<Response> | null = null

    const props = parseRequestProperties(request, clientInfo, transport)
    Object.assign(ctx.props, props)

    log.extend({
        features: props.features,
        tools: props.tools,
        region: props.region,
        version: props.version,
        readOnly: props.readOnly,
        mode: props.mode,
    })
    if (props.mcpConsumer) {
        log.extend({ mcpConsumer: props.mcpConsumer })
    }
    if (props.mcpClientName) {
        log.extend({ mcpClientName: props.mcpClientName })
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

    if (transport === 'streamable-http') {
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
