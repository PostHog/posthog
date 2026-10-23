import { BlockList, isIP } from 'node:net'

import { EDGE_CLIENT_IP_HEADERS, type SignedClientIpOutcome, verifySignedClientIp } from '@/lib/client-ip-signature'

export type ClientIpSource = 'edge' | 'forwarded' | 'cloudflare' | 'none'

// https://www.cloudflare.com/ips/, as of September 2026. Worker subrequests reach the ingress from
// these ranges, so an unsigned request from one of them is Worker traffic that lost its signature.
const CLOUDFLARE_RANGES: [string, number, 'ipv4' | 'ipv6'][] = [
    ['173.245.48.0', 20, 'ipv4'],
    ['103.21.244.0', 22, 'ipv4'],
    ['103.22.200.0', 22, 'ipv4'],
    ['103.31.4.0', 22, 'ipv4'],
    ['141.101.64.0', 18, 'ipv4'],
    ['108.162.192.0', 18, 'ipv4'],
    ['190.93.240.0', 20, 'ipv4'],
    ['188.114.96.0', 20, 'ipv4'],
    ['197.234.240.0', 22, 'ipv4'],
    ['198.41.128.0', 17, 'ipv4'],
    ['162.158.0.0', 15, 'ipv4'],
    ['104.16.0.0', 13, 'ipv4'],
    ['104.24.0.0', 14, 'ipv4'],
    ['172.64.0.0', 13, 'ipv4'],
    ['131.0.72.0', 22, 'ipv4'],
    ['2400:cb00::', 32, 'ipv6'],
    ['2606:4700::', 32, 'ipv6'],
    ['2803:f800::', 32, 'ipv6'],
    ['2405:b500::', 32, 'ipv6'],
    ['2405:8100::', 32, 'ipv6'],
    ['2a06:98c0::', 29, 'ipv6'],
    ['2c0f:f248::', 32, 'ipv6'],
]

const cloudflareAddresses = new BlockList()
for (const [network, prefix, family] of CLOUDFLARE_RANGES) {
    cloudflareAddresses.addSubnet(network, prefix, family)
}

export interface ResolvedClientIp {
    ip: string | undefined
    source: ClientIpSource
    edgeOutcome: SignedClientIpOutcome | 'absent'
}

/**
 * Envoy writes the rightmost X-Forwarded-For entry, so a client cannot forge it. Worker traffic
 * reaches the ingress from a Cloudflare range, so a request from one with no valid edge signature
 * gives no IP.
 */
export async function resolveClientIp(
    headers: Headers,
    edgeSigningKeys: string[],
    nowSeconds?: number
): Promise<ResolvedClientIp> {
    const edgeIp = headers.get(EDGE_CLIENT_IP_HEADERS.ip)
    const edgeTimestamp = headers.get(EDGE_CLIENT_IP_HEADERS.timestamp)
    const edgeSignature = headers.get(EDGE_CLIENT_IP_HEADERS.signature)
    let edgeOutcome: ResolvedClientIp['edgeOutcome'] = 'absent'
    if (edgeIp !== null || edgeTimestamp !== null || edgeSignature !== null) {
        edgeOutcome = await verifySignedClientIp(edgeIp, edgeTimestamp, edgeSignature, edgeSigningKeys, nowSeconds)
        if (edgeOutcome === 'valid' && edgeIp && isIP(edgeIp)) {
            return { ip: edgeIp, source: 'edge', edgeOutcome }
        }
        if (edgeOutcome === 'valid') {
            edgeOutcome = 'invalid_input'
        }
    }

    const forwardedIp = headers.get('x-forwarded-for')?.split(',').at(-1)?.trim()
    const family = forwardedIp ? isIP(forwardedIp) : 0
    if (forwardedIp && family) {
        if (cloudflareAddresses.check(forwardedIp, family === 6 ? 'ipv6' : 'ipv4')) {
            return { ip: undefined, source: 'cloudflare', edgeOutcome }
        }
        return { ip: forwardedIp, source: 'forwarded', edgeOutcome }
    }
    return { ip: undefined, source: 'none', edgeOutcome }
}
