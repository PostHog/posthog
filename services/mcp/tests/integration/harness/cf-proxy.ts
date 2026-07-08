import { createServer } from 'node:net'
import { unstable_dev, type Unstable_DevWorker } from 'wrangler'

import { startHonoHarness } from './hono'
import type { IntegrationEnv, IntegrationHarness } from './types'

// Bind a Node TCP server to port 0 to get a free port, then release it. There's
// a small race vs hard-coded ports, but it keeps the harness parallel-safe.
async function reserveFreePort(): Promise<number> {
    return new Promise((resolve, reject) => {
        const server = createServer()
        server.unref()
        server.once('error', reject)
        server.listen(0, '127.0.0.1', () => {
            const address = server.address()
            if (typeof address === 'object' && address && 'port' in address) {
                const port = address.port
                server.close(() => resolve(port))
            } else {
                server.close(() => reject(new Error('Failed to read assigned port')))
            }
        })
    })
}

// Boots the full proxy stack:
//   1. A Hono listener (with a real Redis on `TEST_REDIS_URL` / db `TEST_REDIS_DB`)
//      pointed at `env.apiBaseUrl` (the local PostHog stack).
//   2. A Cloudflare Worker via `wrangler unstable_dev` running this service's
//      `src/index.ts`, with `MCP_HONO_URL` set to the Hono URL so every
//      proxied request lands on the in-process Hono.
//
// Tests receive the Worker's URL — every assertion travels through the proxy
// → Hono → PostHog backend chain end-to-end. Nothing is mocked.
export async function startCfProxyHarness(env: IntegrationEnv): Promise<IntegrationHarness & { honoUrl: URL }> {
    const hono = await startHonoHarness(env)
    const port = await reserveFreePort()

    let worker: Unstable_DevWorker
    try {
        worker = await unstable_dev('src/index.ts', {
            config: 'wrangler.jsonc',
            local: true,
            ip: '127.0.0.1',
            port,
            // `vars` are baked in at boot — workerd reads them via
            // `cloudflare:workers`'s `env` export. `MCP_HONO_URL` collapses
            // both per-region targets onto the local Hono. `POSTHOG_API_BASE_URL`
            // points the worker's token-probe path at the same backend Hono
            // talks to.
            vars: {
                MCP_HONO_URL: hono.baseUrl.toString().replace(/\/$/, ''),
                POSTHOG_API_BASE_URL: env.apiBaseUrl,
                POSTHOG_ANALYTICS_API_KEY: '',
                POSTHOG_ANALYTICS_HOST: '',
            },
            experimental: {
                disableExperimentalWarning: true,
                disableDevRegistry: true,
            },
            logLevel: 'warn',
        })
    } catch (err) {
        await hono.stop().catch(() => undefined)
        throw err
    }

    return {
        baseUrl: new URL(`http://${worker.address}:${worker.port}`),
        honoUrl: hono.baseUrl,
        stop: async () => {
            await worker.stop().catch(() => undefined)
            await hono.stop().catch(() => undefined)
        },
    }
}
