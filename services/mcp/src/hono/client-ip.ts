import { isIP } from 'node:net'

import { EDGE_CLIENT_IP_HEADERS, type SignedClientIpOutcome, verifySignedClientIp } from '@/lib/client-ip-signature'

export type ClientIpSource = 'edge' | 'forwarded' | 'none'

export interface ResolvedClientIp {
    ip: string | undefined
    source: ClientIpSource
    edgeOutcome: SignedClientIpOutcome | 'absent'
}

/**
 * A failed edge signature gives no IP, because the ingress saw only a Cloudflare address for Worker
 * traffic. Envoy writes the rightmost X-Forwarded-For entry, so a client cannot forge it.
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
