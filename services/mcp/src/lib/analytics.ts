import { env } from 'cloudflare:workers'
import { PostHog } from 'posthog-node'

const POSTHOG_API_KEY = 'sTMFPsFhdP1Ssg'
const POSTHOG_HOST = 'https://us.i.posthog.com'

const DEV_POSTHOG_API_KEY: string | undefined = env.POSTHOG_ANALYTICS_API_KEY ?? POSTHOG_API_KEY
const DEV_POSTHOG_HOST: string | undefined = env.POSTHOG_ANALYTICS_HOST ?? POSTHOG_HOST

let _client: PostHog | undefined

export enum AnalyticsEvent {
    MCP_TOOL_CALL = 'mcp tool call',
    MCP_TOOL_RESPONSE = 'mcp tool response',
    AI_TRACE = '$ai_trace',
    AI_SPAN = '$ai_span',
}

export function generateId(): string {
    return crypto.randomUUID()
}

export const getPostHogClient = (devMode?: boolean): PostHog => {
    if (!_client) {
        const apiKey = devMode ? DEV_POSTHOG_API_KEY : POSTHOG_API_KEY
        const host = devMode ? DEV_POSTHOG_HOST : POSTHOG_HOST
        _client = new PostHog(apiKey, {
            host,
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}
