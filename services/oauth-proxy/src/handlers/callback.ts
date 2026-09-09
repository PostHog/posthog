import { deleteFlowRecord, getFlowRecord } from '@/lib/kv'

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

    const record = await getFlowRecord(kv, state)
    if (!record) {
        return new Response('State expired or invalid', { status: 400 })
    }

    // A transient KV failure here should not turn an already-verified callback into a 500.
    try {
        await deleteFlowRecord(kv, state)
    } catch {
        console.warn(JSON.stringify({ handler: 'callback', error: 'flow_record_delete_failed' }))
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
