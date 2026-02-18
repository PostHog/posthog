import { PostHog } from 'posthog-node'

let _client: PostHog | undefined

export enum AnalyticsEvent {
    MCP_TOOL_CALL = 'mcp tool call',
    MCP_TOOL_RESPONSE = 'mcp tool response',
}

export const getPostHogClient = (): PostHog => {
    if (!_client) {
        _client = new PostHog('sTMFPsFhdP1Ssg', {
            host: 'https://us.i.posthog.com',
            flushAt: 1,
            flushInterval: 0,
        })
    }

    return _client
}
