import { readFileSync } from 'node:fs'

import { PostHogMCP } from '@posthog/mcp-analytics'

import { env } from '@/lib/env'

let _client: PostHogMCP | undefined

export const getMCPServerBuild = (): string | undefined => {
    try {
        const build = readFileSync('/code/commit.txt', 'utf8').trim()
        return build && build !== 'unknown' ? build : undefined
    } catch {
        return undefined
    }
}

// `PostHogMCP` owns canonical MCP events and custom events from `capture()` or
// `captureImmediate()`. Configure `serverBuild` once so the SDK stamps both paths.
export const getPostHogClient = (): PostHogMCP => {
    if (!_client) {
        _client = new PostHogMCP(env.POSTHOG_ANALYTICS_API_KEY ?? '', {
            disabled: !env.POSTHOG_ANALYTICS_API_KEY || !env.POSTHOG_ANALYTICS_HOST, // Disable if the API key or host is not set
            ...(env.POSTHOG_ANALYTICS_HOST ? { host: env.POSTHOG_ANALYTICS_HOST } : {}),
            flushAt: 1,
            flushInterval: 0,
            // Tool errors already surface as `$mcp_is_error: true`; keep the SDK
            // from fanning out a separate `$exception` event into Error Tracking.
            enableExceptionAutocapture: false,
            captureModel: true,
            serverBuild: getMCPServerBuild(),
            before_send: (event) => {
                if (event?.properties?.is_impersonated === true) {
                    return null
                }
                return event
            },
        })
    }

    return _client
}
