import { getCallbackRedirectUri } from '@/lib/kv'

/**
 * OAuth Callback Interception — proxy receives the regional server's callback
 * and forwards to the client's original redirect_uri.
 *
 * This prevents the client from ever seeing the regional server URL, ensuring
 * the client always sends the token exchange back through the proxy.
 */
export async function handleCallback(request: Request, kv: KVNamespace): Promise<Response> {
    const url = new URL(request.url)
    const state = url.searchParams.get('state')

    if (!state) {
        return new Response('Missing state parameter', { status: 400 })
    }

    const originalRedirectUri = await getCallbackRedirectUri(kv, state)
    if (!originalRedirectUri) {
        return new Response('State expired or invalid', { status: 400 })
    }

    // Forward all query params (code, state, error, error_description) to the client
    const clientUrl = new URL(originalRedirectUri)
    for (const [key, value] of url.searchParams.entries()) {
        clientUrl.searchParams.set(key, value)
    }

    return Response.redirect(clientUrl.toString(), 302)
}
