// Shared helpers for building OAuth/auth error responses across both runtimes.
//
// The CF and Hono entry points diverge only in their *observability tail* (CF flushes
// PostHog events via ctx.waitUntil, Hono fires them synchronously). Everything before
// that — permission errors, known error-code mappings, missing/invalid token responses —
// is identical and lives here.

import type { CloudRegion } from '@/tools/types'

import { ErrorCode, findPostHogPermissionError, formatPermissionErrorMessage, PostHogPermissionError } from './errors'
import { isIdJagAccessToken } from './id-jag'
import { buildInsufficientScopeChallenge, InsufficientScopeError, insufficientScopeResponse } from './missing-scope'
import { MCP_DOCS_URL } from './oauth-constants'
import { getPublicUrl } from './routing'

// Map a thrown error to the appropriate auth response, or null if not auth-related.
// Callers handle the null case (typically by emitting observability + returning 500).
export function mapErrorToAuthResponse(error: unknown): Response | null {
    if (error instanceof InsufficientScopeError) {
        return insufficientScopeResponse(error.message, error.challenge)
    }

    const permissionError = findPostHogPermissionError(error)
    if (permissionError) {
        // A request can fail here before token introspection has run, so the API's own challenge
        // is the step-up signal. The API sends one only for a token whose app supports step-up,
        // which is the same token flag introspection reports.
        return insufficientScopeResponse(
            formatPermissionErrorMessage(permissionError),
            permissionError.challengeScopes && buildInsufficientScopeChallenge(permissionError.requiredScopes ?? [])
        )
    }

    if (error instanceof Error) {
        return mapKnownErrorMessage(error.message)
    }

    return null
}

// Other items of a batch may already have run tools, and a step-up client replays the whole
// request after re-consent, so a batch's 403 must not carry the challenge.
export function withoutStepUpChallenge(error: unknown): unknown {
    const permissionError = findPostHogPermissionError(error)
    if (!permissionError?.challengeScopes) {
        return error
    }
    return new PostHogPermissionError({
        detail: permissionError.detail,
        missingScope: permissionError.missingScope,
        url: permissionError.url,
        method: permissionError.method,
    })
}

export function isStepUpChallengeError(error: unknown): boolean {
    return error instanceof InsufficientScopeError || findPostHogPermissionError(error)?.challengeScopes !== undefined
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
    const status = mapErrorToAuthResponse(error)?.status

    if (error instanceof InsufficientScopeError) {
        return { reason: 'insufficient_scope', status, missingScope: error.requiredScopes.join(' ') }
    }
    const permissionError = findPostHogPermissionError(error)
    if (permissionError) {
        const missingScope = permissionError.challengeScopes
            ? permissionError.requiredScopes?.join(' ')
            : permissionError.missingScope
        return { reason: 'insufficient_scope', status, missingScope }
    }

    const message = error instanceof Error ? error.message : ''
    if (message.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
        return { reason: 'inactive_oauth_token', status, missingScope: undefined }
    }
    if (message.includes(ErrorCode.INVALID_API_KEY)) {
        return { reason: 'invalid_api_key', status, missingScope: undefined }
    }
    return { reason: 'unknown', status, missingScope: undefined }
}

// Map a response body string to an auth response if it embeds a known error code.
// Used to translate downstream API errors that surface as 200/4xx with a known
// marker in the body (e.g. SDK transport wrappers).
export function mapKnownErrorMessage(text: string): Response | null {
    if (text.includes(ErrorCode.INACTIVE_OAUTH_TOKEN)) {
        return buildRejectedTokenResponse('OAuth token is inactive')
    }
    if (text.includes(ErrorCode.INVALID_API_KEY)) {
        return buildRejectedTokenResponse('Invalid API key')
    }
    return null
}

// RFC 6750 requires a `WWW-Authenticate` challenge on every 401. Without `error="invalid_token"`,
// an OAuth client reads the 401 as a plain failure and keeps sending the rejected token.
// The challenge has no `resource_metadata`, because the Hono runtime sits behind the worker proxy
// and does not know the origin the client connected to. The worker adds it, and a client that
// connects to Hono directly discovers the metadata from its own server URL.
function buildRejectedTokenResponse(description: string): Response {
    return new Response(description, {
        status: 401,
        headers: { 'WWW-Authenticate': `Bearer error="invalid_token", error_description="${description}"` },
    })
}

export function isRejectedTokenChallenge(response: Response): boolean {
    return response.status === 401 && (response.headers.get('WWW-Authenticate') ?? '').includes('error="invalid_token"')
}

export function isInsufficientScopeChallenge(response: Response): boolean {
    return (
        response.status === 403 &&
        (response.headers.get('WWW-Authenticate') ?? '').includes('error="insufficient_scope"')
    )
}

// The worker answers the protected-resource metadata request, so the metadata URL must name the
// origin the client connected to, not the regional Hono origin that the proxy rewrites it to.
export function withResourceMetadata(
    response: Response,
    request: Request,
    effectiveRegion: CloudRegion | null
): Response {
    const challenge = response.headers.get('WWW-Authenticate')
    if (!challenge) {
        return response
    }
    const rewritten = new Response(response.body, response)
    rewritten.headers.set(
        'WWW-Authenticate',
        `${challenge}, resource_metadata="${buildResourceMetadataUrl(request, effectiveRegion)}"`
    )
    return rewritten
}

// Per RFC 9728, the well-known path goes between the host and the resource path:
// resource /mcp has its metadata at /.well-known/oauth-protected-resource/mcp.
function buildResourceMetadataUrl(request: Request, effectiveRegion: CloudRegion | null): string {
    const metadataUrl = getPublicUrl(request)
    metadataUrl.pathname = `/.well-known/oauth-protected-resource${new URL(request.url).pathname}`
    metadataUrl.search = ''
    if (effectiveRegion) {
        metadataUrl.searchParams.set('region', effectiveRegion)
    }
    return metadataUrl.toString()
}

// Build the RFC 9728 `WWW-Authenticate` response for an unauthenticated request.
// The `resource_metadata` URL points clients at the protected-resource metadata so
// they can discover the authorization server.
export function buildMissingTokenResponse(request: Request, effectiveRegion: CloudRegion | null): Response {
    return new Response(
        `No token provided, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
        {
            status: 401,
            headers: {
                'WWW-Authenticate': `Bearer resource_metadata="${buildResourceMetadataUrl(request, effectiveRegion)}"`,
            },
        }
    )
}

export function buildInvalidTokenFormatResponse(): Response {
    return new Response(
        `Invalid token, please provide a valid API token. View the documentation for more information: ${MCP_DOCS_URL}`,
        { status: 401 }
    )
}

// Validate the bearer token format. Accepts:
//   * Personal API keys (`phx_…`) and OAuth access tokens (`pha_…`).
//   * ID-JAG access tokens — RFC 9068 JWTs with `typ: at+jwt` (issued by the
//     ID-JAG JWT Bearer grant served from the OAuth token endpoint at `/oauth/token`).
// Returns the auth-error response if invalid, or null if the token is well-formed.
export function validateBearerToken(
    token: string | undefined,
    request: Request,
    effectiveRegion: CloudRegion | null
): Response | null {
    if (!token) {
        return buildMissingTokenResponse(request, effectiveRegion)
    }
    if (token.startsWith('phx_') || token.startsWith('pha_')) {
        return null
    }
    if (isIdJagAccessToken(token)) {
        return null
    }
    return buildInvalidTokenFormatResponse()
}
