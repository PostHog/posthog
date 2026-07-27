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
