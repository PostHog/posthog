import { env } from 'cloudflare:workers'
import { PostHog } from 'posthog-node'

let _client: PostHog | undefined

export enum AnalyticsEvent {
    MCP_INIT = 'mcp init',
}

export const getPostHogClient = (): PostHog => {
    if (!_client) {
        _client = new PostHog(env.POSTHOG_ANALYTICS_API_KEY, {
            disabled: !env.POSTHOG_ANALYTICS_API_KEY || !env.POSTHOG_ANALYTICS_HOST, // Disable if the API key or host is not set
            host: env.POSTHOG_ANALYTICS_HOST,
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}

export async function isFeatureFlagEnabled(flagKey: string, distinctId: string): Promise<boolean> {
    try {
        const client = getPostHogClient()
        const result = await client.isFeatureEnabled(flagKey, distinctId)
        return result === true
    } catch {
        return false
    }
}
