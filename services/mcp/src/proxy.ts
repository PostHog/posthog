import { ApiClient } from '@/api/client'
import {
    EDGE_CLIENT_IP_HEADERS,
    MCP_CLIENT_IP_HEADERS,
    parseSigningKeys,
    signedClientIpHeaders,
} from '@/lib/client-ip-signature'
import { env } from '@/lib/env'
import { findPostHogPermissionError } from '@/lib/errors'
import type { CloudRegion } from '@/tools/types'

const MCP_HONO_US_URL = 'https://mcp.us.posthog.com'
const MCP_HONO_EU_URL = 'https://mcp.eu.posthog.com'

const KV_TTL_SECONDS = 7 * 24 * 60 * 60 // 7 days

async function resolveRegion(
    token: string,
    userHash: string,
    kv: KVNamespace | undefined
): Promise<CloudRegion | undefined> {
    if (kv) {
        try {
            const region = await kv.get(`${userHash}:region`)
            if (region) {
                return region as CloudRegion
            }
        } catch (err) {
            console.error('[MCP proxy] error reading cached region:', err)
        }
    }

    // When POSTHOG_API_BASE_URL is set (local dev), both hit the same server —
    // region always resolves to "us", which is correct since local Hono is a
    // single instance. In production, POSTHOG_API_BASE_URL is not set on the
    // CF worker, so this probes both regions in parallel.
    const usBase = env.POSTHOG_API_BASE_URL || 'https://us.posthog.com'
    const euBase = env.POSTHOG_API_BASE_URL || 'https://eu.posthog.com'

    const [usResult, euResult] = await Promise.all([
        new ApiClient({ apiToken: token, baseUrl: usBase }).users().me(),
        new ApiClient({ apiToken: token, baseUrl: euBase }).users().me(),
    ])

    // Only the home region answers 403 (token known, `user:read` missing). The other region answers
    // 401, which would make the client refresh a valid token forever.
    let region: CloudRegion | undefined
    if (usResult.success) {
        region = 'us'
    } else if (euResult.success) {
        region = 'eu'
    } else if (findPostHogPermissionError(usResult.error)) {
        region = 'us'
    } else if (findPostHogPermissionError(euResult.error)) {
        region = 'eu'
    }

    if (region && kv) {
        // A failed cache write must not discard the region the probes resolved.
        try {
            await kv.put(`${userHash}:region`, region, { expirationTtl: KV_TTL_SECONDS })
        } catch (err) {
            console.error('[MCP proxy] error caching region:', err)
        }
    }

    return region
}

function getHonoTargetUrl(region: CloudRegion): string {
    if (env.MCP_HONO_URL) {
        return env.MCP_HONO_URL
    }
    return region === 'eu' ? MCP_HONO_EU_URL : MCP_HONO_US_URL
}

export async function resolveProxyRegion(
    token: string,
    userHash: string,
    kv: KVNamespace | undefined
): Promise<CloudRegion> {
    try {
        const region = await resolveRegion(token, userHash, kv)
        if (region) {
            return region
        }
        console.info('[MCP proxy] could not resolve user region, defaulting to us')
    } catch (err) {
        console.error('[MCP proxy] error resolving region:', err)
    }
    return 'us'
}

export async function honoRequestHeaders(incoming: Headers, region: CloudRegion): Promise<Headers> {
    const headers = new Headers(incoming)
    for (const name of [...Object.values(EDGE_CLIENT_IP_HEADERS), ...Object.values(MCP_CLIENT_IP_HEADERS)]) {
        headers.delete(name)
    }
    // Cloudflare sets CF-Connecting-IP on every request that reaches the Worker, and replaces any
    // value the client sent.
    const clientIp = incoming.get('cf-connecting-ip')
    const keys = parseSigningKeys(
        region === 'eu' ? env.MCP_EDGE_CLIENT_IP_SIGNING_KEYS_EU : env.MCP_EDGE_CLIENT_IP_SIGNING_KEYS_US
    )
    if (clientIp) {
        for (const [name, value] of Object.entries(
            await signedClientIpHeaders(EDGE_CLIENT_IP_HEADERS, keys, clientIp)
        )) {
            headers.set(name, value)
        }
    }
    return headers
}

export async function proxyToHono(request: Request, region: CloudRegion): Promise<Response> {
    const targetBase = getHonoTargetUrl(region)
    const targetUrl = new URL(request.url)
    const target = new URL(targetBase)
    targetUrl.hostname = target.hostname
    targetUrl.protocol = target.protocol
    targetUrl.port = target.port

    return fetch(targetUrl.toString(), {
        method: request.method,
        headers: await honoRequestHeaders(request.headers, region),
        body: request.body,
    })
}
