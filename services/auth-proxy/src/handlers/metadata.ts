/**
 * OAuth 2.0 Authorization Server Metadata (RFC 8414)
 *
 * Returns metadata pointing to oauth.posthog.com endpoints.
 * MCP clients and other OAuth integrations use this to discover where to register,
 * authorize, and exchange tokens.
 */
export function handleMetadata(request: Request): Response {
    const url = new URL(request.url)
    const baseUrl = `${url.protocol}//${url.host}`

    const metadata = {
        issuer: baseUrl,
        authorization_endpoint: `${baseUrl}/oauth/authorize/`,
        token_endpoint: `${baseUrl}/oauth/token/`,
        registration_endpoint: `${baseUrl}/oauth/register/`,
        revocation_endpoint: `${baseUrl}/oauth/revoke/`,
        introspection_endpoint: `${baseUrl}/oauth/introspect/`,
        userinfo_endpoint: `${baseUrl}/oauth/userinfo/`,
        jwks_uri: `${baseUrl}/.well-known/jwks.json`,
        scopes_supported: [
            'openid',
            'profile',
            'email',
            'introspection',
            'action:read',
            'action:write',
            'dashboard:read',
            'dashboard:write',
            'error_tracking:read',
            'error_tracking:write',
            'event_definition:read',
            'event_definition:write',
            'experiment:read',
            'experiment:write',
            'feature_flag:read',
            'feature_flag:write',
            'insight:read',
            'insight:write',
            'logs:read',
            'organization:read',
            'project:read',
            'property_definition:read',
            'query:read',
            'survey:read',
            'survey:write',
            'user:read',
            'warehouse_table:read',
            'warehouse_view:read',
        ],
        response_types_supported: ['code'],
        response_modes_supported: ['query'],
        grant_types_supported: ['authorization_code', 'refresh_token'],
        token_endpoint_auth_methods_supported: ['none', 'client_secret_post'],
        code_challenge_methods_supported: ['S256'],
        service_documentation: 'https://posthog.com/docs/model-context-protocol',
    }

    return new Response(JSON.stringify(metadata), {
        headers: {
            'Content-Type': 'application/json',
            'Cache-Control': 'public, max-age=3600',
        },
    })
}
