/** A setup gap, with an agent prompt and docs. */
export interface InstrumentationFix {
    key: 'intent' | 'sessions' | 'model' | 'harness' | 'identify'
    prompt: string
    docsUrl: string
    emptyState?: { title: string; detail: string }
}

const SDK =
    'My MCP server is instrumented with PostHog MCP analytics (@posthog/mcp for TypeScript or posthog.mcp for Python)'

const DOCS = {
    intent: 'https://posthog.com/docs/mcp-analytics/intent',
    sessions: 'https://posthog.com/docs/mcp-analytics/conversation-id',
    model: 'https://posthog.com/docs/mcp-analytics/installation#capture-the-calling-model',
    harness: 'https://posthog.com/docs/mcp-analytics/custom-servers',
    identify: 'https://posthog.com/docs/mcp-analytics/identifying-users',
}

export const INSTRUMENTATION_FIXES: Record<InstrumentationFix['key'], InstrumentationFix> = {
    intent: {
        key: 'intent',
        docsUrl: DOCS.intent,
        prompt: `${SDK}, but most tool calls arrive without an agent intent. Update the SDK to the latest version, confirm intent capture is enabled on instrument(), and configure the intent fallback so calls where the agent leaves the injected "context" argument empty still get an intent. Follow ${DOCS.intent}.`,
    },
    sessions: {
        key: 'sessions',
        docsUrl: DOCS.sessions,
        prompt: `${SDK}, but almost every tool call lands in its own session. First check which transport the server uses. If requests are request-scoped or reconnect between calls (stateless HTTP, serverless), update the SDK to the latest version and make sure conversation IDs are enabled on instrument(), so the handle the server returns is echoed back by the agent and calls group into sessions. If one long-lived connection already represents one conversation, leave conversation IDs off and tell me why sessions still split. Follow ${DOCS.sessions}.`,
    },
    model: {
        key: 'model',
        docsUrl: DOCS.model,
        emptyState: {
            title: "Models aren't captured",
            detail: 'Tool calls arrive without the model that made them. Turn on model capture to compare errors and latency by model.',
        },
        prompt: `${SDK}, but tool calls arrive without the model that made them. Update the SDK to the latest version and make sure model capture (captureModel in TypeScript, capture_model in Python) is not turned off on instrument(). The SDK reads the model from recognized client metadata first, then from the llm_model argument it adds to each tool schema, so also check that nothing strips that argument from the tool schemas. Follow ${DOCS.model}.`,
    },
    harness: {
        key: 'harness',
        docsUrl: DOCS.harness,
        emptyState: {
            title: "Clients aren't identified",
            detail: 'Almost every call arrives without the name of the app that made it. Pass the client info to the SDK to see calls by harness.',
        },
        prompt: `${SDK}, but almost every tool call shows up as "Unidentified client". Check how the server is wired. If it wraps an MCP server object with instrument(), update the SDK to the latest version. If it uses a custom dispatcher, pass the client name and version from the initialize request (params.clientInfo) and the transport headers to the SDK, as the custom servers guide shows. Follow ${DOCS.harness}.`,
    },
    identify: {
        key: 'identify',
        docsUrl: DOCS.identify,
        emptyState: {
            title: "People aren't identified",
            detail: 'Calls are tied to anonymous session IDs, not people. Add identify to see who uses your server.',
        },
        prompt: `${SDK}, but every tool call is attributed to an anonymous session ID instead of a person. Add an identify callback to instrument() that reads the request's auth (with getRequestHeaders in TypeScript) and returns the user's distinct ID, with their email and name as properties. Use the same distinct ID my product already uses for this user in PostHog. Follow ${DOCS.identify}.`,
    },
}
