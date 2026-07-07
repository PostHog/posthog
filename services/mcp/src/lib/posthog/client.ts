import { PostHogMCP } from '@posthog/mcp-analytics'

import { env } from '@/lib/env'

let _client: PostHogMCP | undefined

// `PostHogMCP` is a drop-in subclass of posthog-node's `PostHog` (capture /
// identify / flush / shutdown all inherited) that adds `captureToolCall` /
// `captureInitialize`. Using it for the shared client means every existing
// `.capture()` callsite keeps working while the hono analytics path gets the
// canonical `$mcp_*` event helpers.
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
        })
    }

    return _client
}
