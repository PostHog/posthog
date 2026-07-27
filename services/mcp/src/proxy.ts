import { ApiClient } from '@/api/client'
import { env } from '@/lib/env'
import type { CloudRegion } from '@/tools/types'

const MCP_HONO_US_URL = 'https://mcp.us.posthog.com'
const MCP_HONO_EU_URL = 'https://mcp.eu.posthog.com'

const KV_TTL_SECONDS = 7 * 24 * 60 * 60 // 7 days

type ResolvedUser = { distinctId: string; region: CloudRegion }

async function resolveUser(
    token: string,
    userHash: string,
    kv: KVNamespace | undefined
): Promise<ResolvedUser | undefined> {
    if (kv) {
        const [distinctId, region] = await Promise.all([
            kv.get(`${userHash}:distinct_id`),
            kv.get(`${userHash}:region`),
        ])
        if (distinctId && region) {
            return { distinctId, region: region as CloudRegion }
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

    let resolved: ResolvedUser | undefined
    if (usResult.success) {
        resolved = { distinctId: usResult.data.distinct_id, region: 'us' }
    } else if (euResult.success) {
        resolved = { distinctId: euResult.data.distinct_id, region: 'eu' }
    }

    if (resolved && kv) {
        await Promise.all([
            kv.put(`${userHash}:distinct_id`, resolved.distinctId, { expirationTtl: KV_TTL_SECONDS }),
            kv.put(`${userHash}:region`, resolved.region, { expirationTtl: KV_TTL_SECONDS }),
        ])
    }

    return resolved
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
        const user = await resolveUser(token, userHash, kv)
        if (user) {
            return user.region
        }
        console.info('[MCP proxy] could not resolve user region, defaulting to us')
    } catch (err) {
        console.error('[MCP proxy] error resolving region:', err)
    }
    return 'us'
}

export function proxyToHono(request: Request, region: CloudRegion): Promise<Response> {
    const targetBase = getHonoTargetUrl(region)
    const targetUrl = new URL(request.url)
    const target = new URL(targetBase)
    targetUrl.hostname = target.hostname
    targetUrl.protocol = target.protocol
    targetUrl.port = target.port

    return fetch(targetUrl.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
    })
}
