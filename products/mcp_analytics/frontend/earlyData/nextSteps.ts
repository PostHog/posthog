import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { SubscriptionApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { INSTRUMENTATION_FIXES, type InstrumentationFix } from '../instrumentationFixes'
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
    | { kind: 'agent-prompt'; fix: InstrumentationFix }
    | { kind: 'weekly-report'; offer: ActionableWeeklyReportOffer }

export type NextStepKey = 'weekly-report' | 'intent' | 'notification'

export type NextStepInteraction = 'open' | 'docs' | 'create-report' | 'open-consent' | 'manage-report' | 'more-options'

export interface NextStep {
    key: NextStepKey
    title: string
    detail: string
    error?: string
    action: NextStepAction
}

/** Below this, instrumentation ratios are noise — hold judgment rather than nag. */
const MIN_CALLS_FOR_SIGNAL = 10

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
export function weeklyReportStep(offer: ActionableWeeklyReportOffer): NextStep {
    return {
        key: 'weekly-report',
        title: offer.state === 'created' ? 'Your weekly report is set up' : 'Get a weekly report in your inbox',
        detail: weeklyReportDetail(offer),
        error: offer.state === 'failed' ? offer.message : undefined,
        action: { kind: 'weekly-report', offer },
    }
}

/** Alerts and reports lead from the first call: new data is the moment to give a reason to come back. */
export function buildNextSteps({ stats, hasFailureNotification, weeklyReport }: NextStepInputs): NextStep[] {
    const enoughSignal = stats.totalCalls >= MIN_CALLS_FOR_SIGNAL
    const intentShare = stats.totalCalls > 0 ? stats.callsWithIntent / stats.totalCalls : 0
    // The weekly report and the failure alert share one step, set up on the Notifications tab.
    const reportPending = weeklyReport.state !== 'hidden' && weeklyReport.state !== 'created'
    // `null` means the count has not loaded; showing the step then would flash and vanish.
    const alertPending = stats.errorCalls > 0 && hasFailureNotification === false

    const steps: NextStep[] = []
    if (reportPending || alertPending) {
        steps.push({
            key: 'notification',
            title: 'Set up alerts and reports',
            detail: 'Get a weekly tool health report by email, and send failed tool calls to Slack, Discord, Microsoft Teams, or a webhook.',
            action: { kind: 'link', label: 'Set up', to: urls.mcpAnalyticsNotifications() },
        })
    }
    if (enoughSignal && intentShare < 0.5) {
        steps.push({
            key: 'intent',
            title: 'Capture what agents are trying to do',
            detail: `Only ${Math.round(intentShare * 100)}% of tool calls carry an agent intent. With it, the feed shows the goal behind every call.`,
            action: { kind: 'agent-prompt', fix: INSTRUMENTATION_FIXES.intent },
        })
    }
    return steps
}
