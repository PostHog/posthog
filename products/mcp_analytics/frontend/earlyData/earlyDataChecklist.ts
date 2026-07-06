export interface EarlyStats {
    totalCalls: number
    distinctTools: number
    distinctSessions: number
    distinctClients: number
    callsWithIntent: number
    errorCalls: number
    missingCapabilityReports: number
}

export type ChecklistStatus = 'ok' | 'warning' | 'pending'

export interface ChecklistItem {
    key: string
    title: string
    detail: string
    status: ChecklistStatus
    docsUrl: string
}

const DOCS = {
    intent: 'https://posthog.com/docs/mcp-analytics/intent',
    conversationId: 'https://posthog.com/docs/mcp-analytics/conversation-id',
    missingCapability: 'https://posthog.com/docs/mcp-analytics/missing-capability',
}

/** Below this, instrumentation ratios are noise — hold judgment rather than warn. */
const MIN_CALLS_FOR_SIGNAL = 10

/**
 * Instrumentation-quality checks for the early-data view. At low volume, better
 * instrumentation is the highest-leverage thing a user can do — every later feature
 * (intent summaries, clustering, sessions) depends on these being wired correctly.
 */
export function buildChecklist(stats: EarlyStats): ChecklistItem[] {
    const enoughSignal = stats.totalCalls >= MIN_CALLS_FOR_SIGNAL

    const intentShare = stats.totalCalls > 0 ? stats.callsWithIntent / stats.totalCalls : 0
    const intentOk = intentShare >= 0.5

    // One session per call means no session state survives between calls
    // (stateless/serverless server) — sessions degrade to singletons.
    const sessionsDegenerate = enoughSignal && stats.distinctSessions >= Math.max(2, Math.floor(stats.totalCalls * 0.9))

    return [
        {
            key: 'intent',
            title: 'Intent capture',
            detail: intentOk
                ? `${Math.round(intentShare * 100)}% of tool calls carry agent intent.`
                : 'Few or no tool calls carry agent intent. Enable the context parameter so you can see what agents are trying to do.',
            status: !enoughSignal ? 'pending' : intentOk ? 'ok' : 'warning',
            docsUrl: DOCS.intent,
        },
        {
            key: 'sessions',
            title: 'Session stitching',
            detail: sessionsDegenerate
                ? 'Almost every tool call starts a new session — typical for stateless or serverless servers. Enable conversation IDs so calls group into real sessions.'
                : 'Tool calls are grouping into sessions.',
            status: !enoughSignal ? 'pending' : sessionsDegenerate ? 'warning' : 'ok',
            docsUrl: DOCS.conversationId,
        },
        {
            key: 'missing-capability',
            title: 'Unmet demand reporting',
            detail:
                stats.missingCapabilityReports > 0
                    ? `Agents have filed ${stats.missingCapabilityReports} missing-capability report${stats.missingCapabilityReports === 1 ? '' : 's'}.`
                    : 'No missing-capability reports yet. Enable reportMissing so agents can tell you which tools they wish you had.',
            status: stats.missingCapabilityReports > 0 ? 'ok' : 'pending',
            docsUrl: DOCS.missingCapability,
        },
    ]
}
