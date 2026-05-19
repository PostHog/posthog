import { PostHog } from 'posthog-node'

import { env } from '@/lib/env'

let _client: PostHog | undefined
export const getPostHogClient = (): PostHog => {
    if (!_client) {
        _client = new PostHog(env.POSTHOG_ANALYTICS_API_KEY ?? '', {
            disabled: !env.POSTHOG_ANALYTICS_API_KEY || !env.POSTHOG_ANALYTICS_HOST, // Disable if the API key or host is not set
            ...(env.POSTHOG_ANALYTICS_HOST ? { host: env.POSTHOG_ANALYTICS_HOST } : {}),
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}
