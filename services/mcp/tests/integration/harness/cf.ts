import { unstable_dev, type Unstable_DevWorker } from 'wrangler'

import type { IntegrationEnv, IntegrationHarness } from './types'

// Boots a real workerd via `wrangler unstable_dev` so the McpAgent framework
// (Durable Objects, blockConcurrencyWhile, agents SDK) runs end-to-end the same
// way it does in production. `local: true` keeps everything on the developer
// machine — no Cloudflare account / network required.
export async function startCfHarness(env: IntegrationEnv): Promise<IntegrationHarness> {
    const worker: Unstable_DevWorker = await unstable_dev('src/index.ts', {
        config: 'wrangler.jsonc',
        local: true,
        // The CF Worker reads `POSTHOG_API_BASE_URL` via the `cloudflare:workers`
        // env binding, not `process.env`. Pass it through `vars` so the binding
        // resolves to the local stack.
        vars: {
            POSTHOG_API_BASE_URL: env.apiBaseUrl,
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
