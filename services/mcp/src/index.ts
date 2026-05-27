import { ApiClient } from '@/api/client'
import { env as runtimeEnv } from '@/lib/env'
import { type RequestLogger, withLogging } from '@/lib/logging'
import { hash } from '@/lib/utils'
import type { CloudRegion } from '@/tools/types'

// Region-aware proxy in front of the Hono MCP server. The worker's only job is
// to figure out which region a request belongs to and forward it to the
// matching Hono backend. All MCP protocol handling, OAuth metadata, auth gating,
// and static asset serving now live in Hono.
//
// Region resolution order:
//   1. Hostname (mcp-eu.posthog.com → eu) — workaround for Claude Code's OAuth
//      bug that ignores authorization_servers metadata and probes
//      /.well-known/oauth-authorization-server on the MCP server directly.
//      See: https://github.com/anthropics/claude-code/issues/2267
//   2. `?region=us|eu` query param.
//   3. Token probe against US + EU /api/users/@me in parallel. Result cached
//      in KV for 7 days, keyed by PBKDF2 hash of the token.
//   4. Default: us.

const MCP_HONO_US_URL = 'https://mcp.us.posthog.com'
const MCP_HONO_EU_URL = 'https://mcp.eu.posthog.com'
const KV_TTL_SECONDS = 7 * 24 * 60 * 60

function regionFromHostname(request: Request): CloudRegion | undefined {
    const url = new URL(request.url)
    const forwardedHost = request.headers.get('X-Forwarded-Host')
    const host = (forwardedHost ?? url.hostname).toLowerCase()
    return host === 'mcp-eu.posthog.com' ? 'eu' : undefined
}

function regionFromQuery(request: Request): CloudRegion | undefined {
    const queryRegion = new URL(request.url).searchParams.get('region')
    return queryRegion === 'us' || queryRegion === 'eu' ? queryRegion : undefined
}

async function regionFromToken(
    token: string,
    userHash: string,
    kv: KVNamespace | undefined
): Promise<CloudRegion | undefined> {
    if (kv) {
        const cached = await kv.get(`${userHash}:region`)
        if (cached === 'us' || cached === 'eu') {
            return cached
        }
    }

    // POSTHOG_API_BASE_URL collapses both probes onto the same dev backend
    // (single Hono instance), so local resolves to "us". In production the var
    // is unset and the worker probes the real US and EU stacks in parallel.
    const usBase = runtimeEnv.POSTHOG_API_BASE_URL || 'https://us.posthog.com'
    const euBase = runtimeEnv.POSTHOG_API_BASE_URL || 'https://eu.posthog.com'

    const [usResult, euResult] = await Promise.all([
        new ApiClient({ apiToken: token, baseUrl: usBase }).users().me(),
        new ApiClient({ apiToken: token, baseUrl: euBase }).users().me(),
    ])

    let resolved: CloudRegion | undefined
    if (usResult.success) {
        resolved = 'us'
    } else if (euResult.success) {
        resolved = 'eu'
    }

    if (resolved && kv) {
        await kv.put(`${userHash}:region`, resolved, { expirationTtl: KV_TTL_SECONDS })
    }

    return resolved
}

async function detectRegion(
    request: Request,
    kv: KVNamespace | undefined,
    log: RequestLogger
): Promise<{ region: CloudRegion; source: string }> {
    const hostnameRegion = regionFromHostname(request)
    if (hostnameRegion) {
        return { region: hostnameRegion, source: 'hostname' }
    }

    const queryRegion = regionFromQuery(request)
    if (queryRegion) {
        return { region: queryRegion, source: 'query' }
    }

    const token = request.headers.get('Authorization')?.split(' ')[1]
    if (token && (token.startsWith('phx_') || token.startsWith('pha_'))) {
        try {
            const tokenRegion = await regionFromToken(token, hash(token), kv)
            if (tokenRegion) {
                return { region: tokenRegion, source: 'token' }
            }
        } catch (err) {
            log.extend({ tokenProbeError: err instanceof Error ? err.message : String(err) })
        }
    }

    return { region: 'us', source: 'default' }
}

function getHonoTargetUrl(region: CloudRegion): string {
    if (runtimeEnv.MCP_HONO_URL) {
        return runtimeEnv.MCP_HONO_URL
    }
    return region === 'eu' ? MCP_HONO_EU_URL : MCP_HONO_US_URL
}

function proxyToHono(request: Request, region: CloudRegion): Promise<Response> {
    const target = new URL(request.url)
    const honoUrl = new URL(getHonoTargetUrl(region))
    target.hostname = honoUrl.hostname
    target.protocol = honoUrl.protocol
    target.port = honoUrl.port

    return fetch(target.toString(), {
        method: request.method,
        headers: request.headers,
        body: request.body,
    })
}

const handleRequest = async (
    request: Request,
    env: Env,
    _ctx: ExecutionContext,
    log: RequestLogger
): Promise<Response> => {
    const { region, source } = await detectRegion(request, env.MCP_KV, log)
    log.extend({ region, regionSource: source, target: getHonoTargetUrl(region) })
    return proxyToHono(request, region)
}

export default {
    fetch: withLogging(handleRequest),
}
