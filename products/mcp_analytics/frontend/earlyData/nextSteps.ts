import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { TOOL_HEALTH_REPORT } from '../notifications/recurringReportDefinitions'
import type { ActionableWeeklyReportOffer, ResolvedWeeklyReportOffer } from '../notifications/weeklyReportOffer'

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
    | { kind: 'weekly-report'; offer: ActionableWeeklyReportOffer }

export type NextStepKey = 'weekly-report' | 'intent' | 'notification' | 'sessions'

export type NextStepInteraction = 'open' | 'docs' | 'create-report' | 'open-consent' | 'manage-report' | 'more-options'

export interface NextStep {
    key: NextStepKey
    title: string
    detail: string
    error?: string
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

export interface NextStepInputs {
    stats: EarlyStats
    hasFailureNotification: boolean | null
    weeklyReport: ResolvedWeeklyReportOffer
}

function weeklyReportDetail(offer: ActionableWeeklyReportOffer): string {
    if (offer.state === 'created') {
        return createdReportDetail(offer.report)
    }
    return `${TOOL_HEALTH_REPORT.lead} First one tomorrow morning to ${offer.email}, then every week.`
}

function createdReportDetail(report: SubscriptionApi): string {
    if (!report.next_delivery_date) {
        return `It goes to ${report.target_value} every week.`
    }
    return `The first one goes to ${report.target_value} on ${dayjs(report.next_delivery_date).format('dddd [at] h:mm A')}.`
}

// The tool health report has something to say on day one. The intent roundup needs intent capture first.
function weeklyReportStep(offer: ActionableWeeklyReportOffer): NextStep {
    return {
        key: 'weekly-report',
        title: offer.state === 'created' ? 'Your weekly report is set up' : 'Get a weekly report in your inbox',
        detail: weeklyReportDetail(offer),
        error: offer.state === 'failed' ? offer.message : undefined,
        action: { kind: 'weekly-report', offer },
    }
}

/**
 * The applicable steps in priority order. A step that is already done is dead space, except the
 * weekly report once created: it stays for the session so the card confirms what the click did.
 * The weekly report leads from the first call, because the moment data arrives is the moment to give a
 * reason to come back.
 */
export function buildNextSteps({ stats, hasFailureNotification, weeklyReport }: NextStepInputs): NextStep[] {
    const enoughSignal = stats.totalCalls >= MIN_CALLS_FOR_SIGNAL
    const intentShare = stats.totalCalls > 0 ? stats.callsWithIntent / stats.totalCalls : 0
    // One session per call means no session state survives between calls
    // (stateless/serverless server) — sessions degrade to singletons. No sessions at all means
    // the calls carry no session ID, which needs the same fix.
    const sessionsDegenerate =
        enoughSignal &&
        (stats.distinctSessions === 0 || stats.distinctSessions >= Math.max(2, Math.ceil(stats.totalCalls * 0.9)))

    const steps: NextStep[] = []
    if (weeklyReport.state !== 'hidden') {
        steps.push(weeklyReportStep(weeklyReport))
    }
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
            detail: `${stats.errorCalls} tool call${stats.errorCalls === 1 ? '' : 's'} failed in the last 30 days. Send new failures to Slack, Discord, Microsoft Teams, or a webhook.`,
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
