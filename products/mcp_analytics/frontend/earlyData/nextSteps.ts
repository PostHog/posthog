import { urls } from 'scenes/urls'

export interface EarlyStats {
    totalCalls: number
    distinctTools: number
    distinctSessions: number
    distinctClients: number
    callsWithIntent: number
    errorCalls: number
    missingCapabilityReports: number
}

export type NextStepAction =
    | { kind: 'link'; label: string; to: string }
    /** A self-contained instruction the user pastes into their coding agent, with the docs as the fallback. */
    | { kind: 'agent-prompt'; prompt: string; docsUrl: string }

export interface NextStep {
    key: 'intent' | 'notification' | 'sessions'
    title: string
    detail: string
    action: NextStepAction
}

const DOCS = {
    intent: 'https://posthog.com/docs/mcp-analytics/intent',
    conversationId: 'https://posthog.com/docs/mcp-analytics/conversation-id',
}

const INTENT_PROMPT = `My MCP server is instrumented with PostHog MCP analytics (@posthog/mcp for TypeScript or posthog.mcp for Python), but most tool calls arrive without an agent intent. Update the SDK to the latest version, confirm intent capture is enabled on instrument(), and configure the intent fallback so calls where the agent leaves the injected "context" argument empty still get an intent. Follow ${DOCS.intent}.`

const SESSIONS_PROMPT = `My MCP server is instrumented with PostHog MCP analytics (@posthog/mcp for TypeScript or posthog.mcp for Python), but almost every tool call lands in its own session. First check which transport the server uses. If requests are request-scoped or reconnect between calls (stateless HTTP, serverless), update the SDK to the latest version and make sure conversation IDs are enabled on instrument(), so the handle the server returns is echoed back by the agent and calls group into sessions. If one long-lived connection already represents one conversation, leave conversation IDs off and tell me why sessions still split. Follow ${DOCS.conversationId}.`

/** Below this, instrumentation ratios are noise — hold judgment rather than nag. */
const MIN_CALLS_FOR_SIGNAL = 10

/** More than this and the card competes with the feed for attention. */
const MAX_STEPS = 3

/** Only the applicable steps, in priority order: a step that is already done is dead space. */
export function buildNextSteps(stats: EarlyStats, hasFailureNotification: boolean | null): NextStep[] {
    const enoughSignal = stats.totalCalls >= MIN_CALLS_FOR_SIGNAL
    const intentShare = stats.totalCalls > 0 ? stats.callsWithIntent / stats.totalCalls : 0
    // One session per call means no session state survives between calls
    // (stateless/serverless server) — sessions degrade to singletons. No sessions at all means
    // the calls carry no session ID, which needs the same fix.
    const sessionsDegenerate =
        enoughSignal &&
        (stats.distinctSessions === 0 || stats.distinctSessions >= Math.max(2, Math.ceil(stats.totalCalls * 0.9)))

    const steps: NextStep[] = []
    if (enoughSignal && intentShare < 0.5) {
        steps.push({
            key: 'intent',
            title: 'Capture what agents are trying to do',
            detail: `Only ${Math.round(intentShare * 100)}% of tool calls carry an agent intent. With it, the feed shows the goal behind every call.`,
            action: { kind: 'agent-prompt', prompt: INTENT_PROMPT, docsUrl: DOCS.intent },
        })
    }
    // `null` means the count has not loaded; showing the step then would flash and vanish.
    if (stats.errorCalls > 0 && hasFailureNotification === false) {
        steps.push({
            key: 'notification',
            title: 'Get alerted when a tool call fails',
            detail: `${stats.errorCalls} tool call${stats.errorCalls === 1 ? '' : 's'} failed in the last 30 days. Send new failures to Slack, email, or a webhook.`,
            action: { kind: 'link', label: 'Set up an alert', to: urls.mcpAnalyticsNotifications() },
        })
    }
    if (sessionsDegenerate) {
        steps.push({
            key: 'sessions',
            title: 'Group tool calls into sessions',
            detail: 'Almost every call starts a new session, which is typical for stateless servers. Conversation IDs stitch them together.',
            action: { kind: 'agent-prompt', prompt: SESSIONS_PROMPT, docsUrl: DOCS.conversationId },
        })
    }
    return steps.slice(0, MAX_STEPS)
}
