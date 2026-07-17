// RFC 9068 `typ` for OAuth 2.0 access tokens. ID-JAG access tokens
// (`posthog.api.id_jag`) are issued with this header so the resource server
// can distinguish them from sharing/export JWTs.
const ID_JAG_ACCESS_TOKEN_TYPE = 'at+jwt'

function base64UrlToBase64(input: string): string {
    const replaced = input.replace(/-/g, '+').replace(/_/g, '/')
    const padding = (4 - (replaced.length % 4)) % 4
    return replaced + '='.repeat(padding)
}

// Cheap header-only inspection — signature verification is the PostHog API's
// job (`IDJagAccessTokenAuthentication` in `posthog/auth.py`). We just need
// to recognize the token so we don't reject it at the MCP gate.
export function isIdJagAccessToken(token: string): boolean {
    const segments = token.split('.')
    if (segments.length !== 3) {
        return false
    }
    try {
        const headerRaw = segments[0]
        if (!headerRaw) {
            return false
        }
        const headerJson = atob(base64UrlToBase64(headerRaw))
        const header = JSON.parse(headerJson) as { typ?: unknown }
        return header.typ === ID_JAG_ACCESS_TOKEN_TYPE
    } catch {
        return false
    }
}

export interface IdJagAuthorizationMetadata {
    scopes: string[]
    scopedOrganizations: string[]
}

/**
 * Read authorization metadata from an ID-JAG access token after the PostHog
 * API has authenticated that same token via `/api/users/@me/`.
 *
 * This helper does not verify the JWT signature. Callers must first authenticate
 * the token with PostHog, which is the resource server and source of truth for
 * signature, expiry, audience, membership, and entitlement validation.
 */
export function readIdJagAuthorizationMetadata(token: string): IdJagAuthorizationMetadata | null {
    if (!isIdJagAccessToken(token)) {
        return null
    }
    try {
        const payloadRaw = token.split('.')[1]
        if (!payloadRaw) {
            return null
        }
        const payloadJson = atob(base64UrlToBase64(payloadRaw))
        const payload = JSON.parse(payloadJson) as { scope?: unknown; org_id?: unknown }
        const scopes = typeof payload.scope === 'string' ? payload.scope.split(/\s+/).filter(Boolean) : []
        const scopedOrganizations = typeof payload.org_id === 'string' && payload.org_id ? [payload.org_id] : []
        return { scopes, scopedOrganizations }
    } catch {
        return null
    }
}
