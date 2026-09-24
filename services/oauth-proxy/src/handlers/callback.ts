import { getPendingCallback } from '@/lib/kv'

import CALLBACK_ERROR_HTML from '../static/callback-error.html'

const CALLBACK_ERROR_HEADERS: Record<string, string> = {
    'Content-Type': 'text/html; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Frame-Options': 'DENY',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
}

/**
 * The proxy holds the only copy of the client's `redirect_uri`, so a callback it cannot
 * match to a flow has nowhere to send the authorization code. Say so in a page the person
 * can act on instead of a bare 400, which leaves them on a dead URL with no way forward.
 */
function flowNotFound(): Response {
    return new Response(CALLBACK_ERROR_HTML, { status: 400, headers: CALLBACK_ERROR_HEADERS })
}

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
        return flowNotFound()
    }

    // Left to expire on its TTL rather than consumed on read: deleting it made the forward
    // single-use, so a reload or a client retry dropped a code the person had already granted.
    // Replaying is inert, because the regional server redeems a code once and PKCE binds it.
    const record = await getPendingCallback(kv, state)
    if (!record) {
        return flowNotFound()
    }

    const clientUrl = new URL(record.redirect_uri)
    for (const [key, value] of url.searchParams.entries()) {
        if (key === 'state') {
            continue
        }
        clientUrl.searchParams.set(key, value)
    }
    if (record.state !== null) {
        clientUrl.searchParams.set('state', record.state)
    }

    return Response.redirect(clientUrl.toString(), 302)
}
