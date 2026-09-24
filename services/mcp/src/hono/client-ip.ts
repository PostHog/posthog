import { isIP } from 'node:net'

import { EDGE_CLIENT_IP_HEADERS, type SignedClientIpOutcome, verifySignedClientIp } from '@/lib/client-ip-signature'

export type ClientIpSource = 'edge' | 'forwarded' | 'none'

export interface ResolvedClientIp {
    ip: string | undefined
    source: ClientIpSource
    edgeOutcome: SignedClientIpOutcome | 'absent'
}

/**
 * A request from the Cloudflare Worker carries the IP that the Worker signed. The ingress saw only
 * a Cloudflare address for it, so an edge signature that fails to verify gives no IP rather than a
 * fallback to X-Forwarded-For. A request without edge headers came straight through the ingress,
 * and Envoy writes the rightmost X-Forwarded-For entry. It does so whether it replaces the header
 * or appends to it, so a client cannot forge that entry.
 */
export async function resolveClientIp(
    headers: Headers,
    edgeSigningKeys: string[],
    nowSeconds?: number
): Promise<ResolvedClientIp> {
    const edgeIp = headers.get(EDGE_CLIENT_IP_HEADERS.ip)
    const edgeTimestamp = headers.get(EDGE_CLIENT_IP_HEADERS.timestamp)
    const edgeSignature = headers.get(EDGE_CLIENT_IP_HEADERS.signature)
    if (edgeIp !== null || edgeTimestamp !== null || edgeSignature !== null) {
        const edgeOutcome = await verifySignedClientIp(
            edgeIp,
            edgeTimestamp,
            edgeSignature,
            edgeSigningKeys,
            nowSeconds
        )
        if (edgeOutcome === 'valid' && edgeIp && isIP(edgeIp)) {
            return { ip: edgeIp, source: 'edge', edgeOutcome }
        }
        return { ip: undefined, source: 'none', edgeOutcome: edgeOutcome === 'valid' ? 'invalid_input' : edgeOutcome }
    }

    const forwardedIp = headers.get('x-forwarded-for')?.split(',').at(-1)?.trim()
    if (forwardedIp && isIP(forwardedIp)) {
        return { ip: forwardedIp, source: 'forwarded', edgeOutcome: 'absent' }
    }
    return { ip: undefined, source: 'none', edgeOutcome: 'absent' }
}
