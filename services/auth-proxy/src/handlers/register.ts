import { POSTHOG_EU_BASE_URL, POSTHOG_US_BASE_URL } from '@/lib/constants'
import type { ClientMapping } from '@/lib/kv'
import { putClientMapping } from '@/lib/kv'

/**
 * Dynamic Client Registration (RFC 7591) — dual-register proxy.
 *
 * Registers the client on BOTH US and EU PostHog instances simultaneously,
 * then stores the mapping and returns a proxy client_id to the caller.
 *
 * The proxy client_id is the US client_id by convention — the mapping in KV
 * lets us translate to the EU client_id when needed.
 */
export async function handleRegister(request: Request, kv: KVNamespace): Promise<Response> {
    const body = await request.text()
    const headers = new Headers(request.headers)
    headers.delete('host')

    const [usResponse, euResponse] = await Promise.all([
        fetch(`${POSTHOG_US_BASE_URL}/oauth/register/`, {
            method: 'POST',
            headers,
            body,
        }),
        fetch(`${POSTHOG_EU_BASE_URL}/oauth/register/`, {
            method: 'POST',
            headers: new Headers(request.headers),
            body,
        }),
    ])

    const usData = await usResponse.json<Record<string, unknown>>()
    const euData = await euResponse.json<Record<string, unknown>>()

    // If both registrations failed, return the US error
    if (!usResponse.ok && !euResponse.ok) {
        return new Response(JSON.stringify(usData), {
            status: usResponse.status,
            headers: { 'Content-Type': 'application/json' },
        })
    }

    // Use the US client_id as the proxy client_id (convention)
    // If US failed but EU succeeded, use EU as the proxy client_id
    const primaryData = usResponse.ok ? usData : euData
    const proxyClientId = primaryData.client_id as string

    const mapping: ClientMapping = {
        us_client_id: usResponse.ok ? (usData.client_id as string) : '',
        eu_client_id: euResponse.ok ? (euData.client_id as string) : '',
        created_at: Date.now(),
    }

    // Store client secrets for confidential clients
    if (usData.client_secret) {
        mapping.us_client_secret = usData.client_secret as string
    }
    if (euData.client_secret) {
        mapping.eu_client_secret = euData.client_secret as string
    }

    await putClientMapping(kv, proxyClientId, mapping)

    return new Response(JSON.stringify(primaryData), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
    })
}
