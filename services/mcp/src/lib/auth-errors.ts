// Shared helpers for building OAuth/auth error responses across both runtimes.
//
// The CF and Hono entry points diverge only in their *observability tail* (CF flushes
// PostHog events via ctx.waitUntil, Hono fires them synchronously). Everything before
// that — permission errors, known error-code mappings, missing/invalid token responses —
// is identical and lives here.

import type { CloudRegion } from '@/tools/types'

import { MCP_DOCS_URL } from './oauth-constants'
import {
    buildInsufficientScopeChallenge,
    ErrorCode,
    findPostHogPermissionError,
    formatPermissionErrorMessage,
} from './errors'
import { getPublicUrl } from './routing'

// Map a thrown error to the appropriate auth response, or null if not auth-related.
// Callers handle the null case (typically by emitting observability + returning 500).
export function mapErrorToAuthResponse(error: unknown): Response | null {
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

    if (error instanceof Error) {
        return mapKnownErrorMessage(error.message)
    }

    return null
}

// Map a response body string to an auth response if it embeds a known error code.
// Used to translate downstream API errors that surface as 200/4xx with a known
// marker in the body (e.g. SDK transport wrappers).
export function mapKnownErrorMessage(text: string): Response | null {
    if (text.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
        return new Response('OAuth token is inactive', { status: 401 })
    }
    if (text.includes(ErrorCode.INVALID_API_KEY)) {
        return new Response('Invalid API key', { status: 401 })
    }
    return null
}

// Build the RFC 9728 `WWW-Authenticate` response for an unauthenticated request.
// The `resource_metadata` URL points clients at the protected-resource metadata so
// they can discover the authorization server.
export function buildMissingTokenResponse(request: Request, effectiveRegion: CloudRegion | null): Response {
    const url = new URL(request.url)
    const metadataUrl = getPublicUrl(request)
    metadataUrl.pathname = `/.well-known/oauth-protected-resource${url.pathname}`
    metadataUrl.search = ''
    if (effectiveRegion) {
        metadataUrl.searchParams.set('region', effectiveRegion)
    }

    return new Response(
        `No token provided, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
        {
            status: 401,
            headers: { 'WWW-Authenticate': `Bearer resource_metadata="${metadataUrl.toString()}"` },
        }
    )
}

export function buildInvalidTokenFormatResponse(): Response {
    return new Response(
        `Invalid token, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
        { status: 401 }
    )
}

// Validate the bearer token format (must be present and `phx_`/`pha_` prefixed).
// Returns the auth-error response if invalid, or null if the token is well-formed.
export function validateBearerToken(
    token: string | undefined,
    request: Request,
    effectiveRegion: CloudRegion | null
): Response | null {
    if (!token) {
        return buildMissingTokenResponse(request, effectiveRegion)
    }
    if (!token.startsWith('phx_') && !token.startsWith('pha_')) {
        return buildInvalidTokenFormatResponse()
    }
    return null
}
