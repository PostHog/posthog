import { createServer } from 'node:net'
import { unstable_dev, type Unstable_DevWorker } from 'wrangler'

import type { IntegrationEnv, IntegrationHarness } from './types'

// `vars` are baked into workerd at boot, so we need MCP_APPS_BASE_URL to know
// the listener's port up-front. Bind a Node TCP server to port 0, read the
// kernel-assigned port, then close — workerd grabs that port a moment later.
// Tiny race window vs hardcoding a fixed port; tests stay parallel-safe.
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

// Boots a real workerd via `wrangler unstable_dev` so the McpAgent framework
// (Durable Objects, blockConcurrencyWhile, agents SDK) runs end-to-end the same
// way it does in production. `local: true` keeps everything on the developer
// machine — no Cloudflare account / network required.
export async function startCfHarness(env: IntegrationEnv): Promise<IntegrationHarness> {
    const port = await reserveFreePort()
    const baseUrl = new URL(`http://127.0.0.1:${port}`)

    const worker: Unstable_DevWorker = await unstable_dev('src/index.ts', {
        config: 'wrangler.jsonc',
        local: true,
        ip: '127.0.0.1',
        port,
        // The CF Worker reads `POSTHOG_API_BASE_URL` via the `cloudflare:workers`
        // env binding, not `process.env`. Pass it through `vars` so the binding
        // resolves to the local stack. `MCP_APPS_BASE_URL` overrides the value
        // hard-coded in `wrangler.jsonc` (which points at the production worker).
        vars: {
            POSTHOG_API_BASE_URL: env.apiBaseUrl,
            MCP_APPS_BASE_URL: baseUrl.toString().replace(/\/$/, ''),
            // Match the workers vitest config — empty values keep observability
            // paths short-circuited and silence the analytics no-network warning.
            POSTHOG_ANALYTICS_API_KEY: '',
            POSTHOG_ANALYTICS_HOST: '',
            POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: '',
            POSTHOG_UI_APPS_TOKEN: '',
            INKEEP_API_KEY: '',
            MCP_CAT_PROJECT_ID: '',
        },
        experimental: {
            disableExperimentalWarning: true,
            disableDevRegistry: true,
        },
        // Quiet the dev-server console output so test runs aren't drowned out.
        logLevel: 'warn',
    })

    return {
        baseUrl: new URL(`http://${worker.address}:${worker.port}`),
        stop: () => worker.stop(),
    }
}
