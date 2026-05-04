/**
 * OAuth 2.0 Authorization Server Metadata (RFC 8414)
 *
 * Returns metadata pointing to oauth.posthog.com endpoints.
 * MCP clients and other OAuth integrations use this to discover where to register,
 * authorize, and exchange tokens.
 *
 * We always cache the information exposed by the authoritative source - us.posthog.com
 * and simply alter the endpoint-related fields to point to oauth.posthog.com.
 *
 * The actual underlying metadata is defined in posthog/api/oauth/views.py#OAuthAuthorizationServerMetadataView.get()
 */

interface WellKnownOAuthAuthorizationServerMetadata {
    issuer: string
    authorization_endpoint: string
    token_endpoint: string
    revocation_endpoint: string
    introspection_endpoint: string
    userinfo_endpoint: string
    jwks_uri: string
    registration_endpoint: string
    scopes_supported: string[]
    response_types_supported: string[]
    response_modes_supported: string[]
    grant_types_supported: string[]
    token_endpoint_auth_methods_supported: string[]
    code_challenge_methods_supported: string[]
    service_documentation: string
    client_id_metadata_document_supported: boolean
}

let authoritativeMetadataCache: WellKnownOAuthAuthorizationServerMetadata | null = null
let cachedUntil: Date | null = null

// We do not have to worry about local development since the proxy is not used when developing the MCP locally.
async function fetchAuthoritativeMetadata(): Promise<WellKnownOAuthAuthorizationServerMetadata> {
    const response = await fetch('https://us.posthog.com/.well-known/oauth-authorization-server')
    if (!response.ok) {
        throw new Error(`Failed to fetch authoritative metadata: ${response.statusText}`)
    }

    return response.json() as Promise<WellKnownOAuthAuthorizationServerMetadata>
}

export async function handleMetadata(request: Request): Promise<Response> {
    if (!authoritativeMetadataCache || !cachedUntil || cachedUntil < new Date()) {
        try {
            authoritativeMetadataCache = await fetchAuthoritativeMetadata()
            cachedUntil = new Date(Date.now() + 600 * 1000) // cache for 10 minutes (600 seconds)
        } catch (error) {
            console.error('Failed to fetch metadata:', error)
            return new Response(
                JSON.stringify({
                    error: 'server_error',
                    error_description: 'Unable to fetch authorization server metadata',
                }),
                { status: 502, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
            )
        }
    }

    const url = new URL(request.url)
    const baseUrl = `${url.protocol}//${url.host}`

    // Alter the endpoint-related fields to point to the oauth.posthog.com base domain.
    const metadata: WellKnownOAuthAuthorizationServerMetadata = {
        ...authoritativeMetadataCache,
        issuer: baseUrl,
        authorization_endpoint: `${baseUrl}/oauth/authorize/`,
        token_endpoint: `${baseUrl}/oauth/token/`,
        revocation_endpoint: `${baseUrl}/oauth/revoke/`,
        introspection_endpoint: `${baseUrl}/oauth/introspect/`,
        userinfo_endpoint: `${baseUrl}/oauth/userinfo/`,
        jwks_uri: `${baseUrl}/.well-known/jwks.json`,
        registration_endpoint: `${baseUrl}/oauth/register/`,
    }

    return new Response(JSON.stringify(metadata), {
        headers: {
            'Content-Type': 'application/json',
            'Cache-Control': 'public, max-age=3600',
        },
    })
}
