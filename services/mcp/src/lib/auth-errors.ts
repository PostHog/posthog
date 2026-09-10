// Shared helpers for building OAuth/auth error responses across both runtimes.
//
// The CF and Hono entry points diverge only in their *observability tail* (CF flushes
// PostHog events via ctx.waitUntil, Hono fires them synchronously). Everything before
// that — permission errors, known error-code mappings, missing/invalid token responses —
// is identical and lives here.

import {
    buildInsufficientScopeChallenge,
    ErrorCode,
    findPostHogPermissionError,
    formatPermissionErrorMessage,
} from './errors'
import { isIdJagAccessToken } from './id-jag'
import { MCP_DOCS_URL } from './oauth-constants'
import { getPublicUrl, getRegionFromRequest } from './routing'

// Map a thrown error to the appropriate auth response, or null if not auth-related.
// Callers handle the null case (typically by emitting observability + returning 500).
// `request` is required because every response built here reaches a client, and a 401
// only tells the client to re-authorize when it carries the `WWW-Authenticate` header.
export function mapErrorToAuthResponse(error: unknown, request: Request): Response | null {
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
        return mapKnownErrorMessage(error.message, request)
    }

    return null
}

export type McpAuthFailureReason =
    | 'insufficient_scope'
    | 'inactive_oauth_token'
    | 'invalid_api_key'
    | 'missing_token'
    | 'invalid_token_format'
    | 'unknown'

export interface McpAuthFailure {
    reason: McpAuthFailureReason
    status: number | undefined
    missingScope: string | undefined
}

export function classifyAuthFailure(error: unknown): McpAuthFailure {
    const permissionError = findPostHogPermissionError(error)
    if (permissionError) {
        return { reason: 'insufficient_scope', status: 403, missingScope: permissionError.missingScope }
    }

    const message = error instanceof Error ? error.message : ''
    if (message.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
        return { reason: 'inactive_oauth_token', status: 401, missingScope: undefined }
    }
    if (message.includes(ErrorCode.INVALID_API_KEY)) {
        return { reason: 'invalid_api_key', status: 401, missingScope: undefined }
    }
    return { reason: 'unknown', status: undefined, missingScope: undefined }
}

// Whether the error answers the client with a 401/403 rather than a 500. Callers that
// need only the verdict use this instead of building a response they discard.
export function isAuthError(error: unknown): boolean {
    return classifyAuthFailure(error).reason !== 'unknown'
}

// Map a response body string to an auth response if it embeds a known error code.
// Used to translate downstream API errors that surface as 200/4xx with a known
// marker in the body (e.g. SDK transport wrappers).
export function mapKnownErrorMessage(text: string, request: Request): Response | null {
    if (text.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
        return buildInvalidTokenResponse('OAuth token is inactive', request)
    }
    if (text.includes(ErrorCode.INVALID_API_KEY)) {
        return buildInvalidTokenResponse('Invalid API key', request)
    }
    return null
}

// Build the RFC 9728 `resource_metadata` URL for the resource this request addressed.
// The region pin matters: a client that rediscovers without it can be sent to the
// wrong regional authorization server, which mints a token this resource rejects.
function buildResourceMetadataUrl(request: Request): string {
    const metadataUrl = getPublicUrl(request)
    metadataUrl.pathname = `/.well-known/oauth-protected-resource${metadataUrl.pathname}`
    metadataUrl.search = ''
    const region = getRegionFromRequest(request)
    if (region) {
        metadataUrl.searchParams.set('region', region)
    }
    return metadataUrl.toString()
}

// Build the RFC 6750 `invalid_token` challenge. A 401 without it reads to a client as
// a plain failure, so it keeps replaying a token the resource server will never accept
// again. `error="invalid_token"` is what tells the client to re-run authorization.
function buildInvalidTokenChallenge(description: string, request: Request): string {
    return [
        'Bearer error="invalid_token"',
        `error_description="${description}"`,
        `resource_metadata="${buildResourceMetadataUrl(request)}"`,
    ].join(', ')
}

// A 401 for a token that was present but rejected. RFC 6750 section 3 requires the
// `WWW-Authenticate` header on every such response.
function buildInvalidTokenResponse(body: string, request: Request, description: string = body): Response {
    return new Response(body, {
        status: 401,
        headers: { 'WWW-Authenticate': buildInvalidTokenChallenge(description, request) },
    })
}

// Build the RFC 9728 `WWW-Authenticate` response for an unauthenticated request.
// The `resource_metadata` URL points clients at the protected-resource metadata so
// they can discover the authorization server.
export function buildMissingTokenResponse(request: Request): Response {
    return new Response(
        `No token provided, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
        {
            status: 401,
            headers: { 'WWW-Authenticate': `Bearer resource_metadata="${buildResourceMetadataUrl(request)}"` },
        }
    )
}

export function buildInvalidTokenFormatResponse(request: Request): Response {
    return buildInvalidTokenResponse(
        `Invalid token, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
        request,
        'Invalid token format'
    )
}

// Validate the bearer token format. Accepts:
//   * Personal API keys (`phx_…`) and OAuth access tokens (`pha_…`).
//   * ID-JAG access tokens — RFC 9068 JWTs with `typ: at+jwt` (issued by the
//     ID-JAG JWT Bearer grant served from the OAuth token endpoint at `/oauth/token`).
// Returns the auth-error response if invalid, or null if the token is well-formed.
export function validateBearerToken(token: string | undefined, request: Request): Response | null {
    if (!token) {
        return buildMissingTokenResponse(request)
    }
    if (token.startsWith('phx_') || token.startsWith('pha_')) {
        return null
    }
    if (isIdJagAccessToken(token)) {
        return null
    }
    return buildInvalidTokenFormatResponse(request)
}
