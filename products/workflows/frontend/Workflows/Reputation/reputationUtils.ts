import type { LemonTagType } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import type { WorkflowEmailSendingRatesApi } from 'products/workflows/frontend/generated/api.schemas'

import type { ReputationActionSeverity } from './reputationActions'

export const REPUTATION_DOCS_URL = 'https://posthog.com/docs/workflows/sending-reputation'
export const SENDING_TIERS_DOCS_URL = `${REPUTATION_DOCS_URL}#sending-allowance-tiers`
export const CONFIGURE_CHANNELS_DOCS_URL = 'https://posthog.com/docs/workflows/configure-channels'

// Must match the endpoint's window (HogFlowViewSet.REPUTATION_WINDOW_DAYS) and cap
// (HogFlowViewSet.WORKFLOW_REPUTATION_LIMIT).
export const WINDOW_TOOLTIP = 'Calculated over your workflow email from the last 30 days.'
export const WORKFLOW_LIMIT = 50

export function formatRate(rate: number): string {
    return percentage(rate, 2, true)
}

export type RateKind = 'bounce' | 'complaint'

export const RATE_KINDS: Record<RateKind, { event: string; events: string; findingType: 'BOUNCE' | 'COMPLAINT' }> = {
    bounce: { event: 'bounce', events: 'bounces', findingType: 'BOUNCE' },
    complaint: { event: 'spam complaint', events: 'spam complaints', findingType: 'COMPLAINT' },
}

export const SEVERITY_STYLE: Record<
    ReputationActionSeverity,
    { label: string; tagType: LemonTagType; border: string }
> = {
    high: { label: 'Fix now', tagType: 'danger', border: 'border-l-danger' },
    medium: { label: 'Needs attention', tagType: 'warning', border: 'border-l-warning' },
    low: { label: 'Worth a look', tagType: 'muted', border: 'border-l-muted' },
}

/** An unnamed workflow shows its id, so the action list and the table name it the same way. */
export function workflowName(workflow: WorkflowEmailSendingRatesApi): string {
    return workflow.hog_flow_name || workflow.hog_flow_id
}

// Per-workflow rate classification. Reserved words like "Warning" / "Critical" belong to the
// tenant-level AWS verdict. These coarser buckets are a triage aid for spotting which workflows
// pull the project's numbers in the wrong direction.
//
// Thresholds mirror SES's account-level reputation dashboard warning lines (bounce: 5% review /
// 10% pause; complaint: 0.1% review / 0.5% pause), deliberately conservative early warnings.
// Actual tenant enforcement (the Standard reputation policy) pauses much higher, with high-severity
// findings at >15% bounce / >1% complaint, so a "high" rate here means "fix this now", not
// "sending is about to stop". Sources:
// https://docs.aws.amazon.com/ses/latest/dg/reputationdashboardmessages.html (dashboard lines)
// https://aws.amazon.com/blogs/messaging-and-targeting/implement-tenants-in-your-amazon-ses-environment-part-3-implementation-guide/ (tenant policy lines)
export const RATE_THRESHOLDS = {
    bounce: { elevated: 0.03, high: 0.05 },
    complaint: { elevated: 0.001, high: 0.005 },
} as const

export type RateLevel = 'healthy' | 'elevated' | 'high'

// Below this much volume one event on its own clears the elevated line, so a verdict would be
// reporting noise: one bounce in 20 sends reads as 5%.
export function minimumVolumeToClassify(kind: RateKind): number {
    return Math.ceil(1 / RATE_THRESHOLDS[kind].elevated)
}

export function classifyRate(rate: number, kind: RateKind): RateLevel {
    const thresholds = RATE_THRESHOLDS[kind]
    if (rate >= thresholds.high) {
        return 'high'
    }
    if (rate >= thresholds.elevated) {
        return 'elevated'
    }
    return 'healthy'
}

// SES names providers as one capitalized word, which is not how people write most of them. Only
// the names that read wrong are listed; anything absent is shown as SES reports it, so a provider
// added to SES_ISP_DIMENSIONS still renders without a matching entry here. `__other__` is the
// backend's name for the volume it could not attribute to any of them.
export const OTHER_ISP = '__other__'

const ISP_DISPLAY_NAMES: Record<string, string> = {
    Aol: 'AOL',
    Gmx: 'GMX',
    Icloud: 'Apple iCloud',
    [OTHER_ISP]: 'Other providers',
}

export function ispDisplayName(isp: string): string {
    return ISP_DISPLAY_NAMES[isp] ?? isp
}
