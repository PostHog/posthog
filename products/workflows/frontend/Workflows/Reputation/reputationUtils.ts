import type { LemonTagType } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'

import type {
    AwsTenantReputationApi,
    WorkflowEmailSendingRatesApi,
} from 'products/workflows/frontend/generated/api.schemas'

import type { ReputationAction, ReputationActionSeverity } from './actions/reputationActionTypes'

export const REPUTATION_DOCS_URL = 'https://posthog.com/docs/workflows/sending-reputation'
// pinned: the anchors below are headings on posthog.com, so renaming a heading breaks its link
export const SENDING_TIERS_DOCS_URL = `${REPUTATION_DOCS_URL}#sending-allowance-tiers`
export const LOWER_RATES_DOCS_URL = `${REPUTATION_DOCS_URL}#how-do-i-keep-my-bounce-and-complaint-rates-low`
export const CHANNEL_SETUP_DOCS_URL =
    'https://posthog.com/docs/workflows/configure-channels#create-a-new-workflows-channel'

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

// Complaints come first: their lines are far lower than the bounce lines, and the endpoint ranks
// workflows by complaint rate for the same reason.
export const RATE_KIND_LIST: readonly RateKind[] = ['complaint', 'bounce']

type ReputationActionTone = 'blocking' | ReputationActionSeverity

// Red is only for items that stop email going out. The rest step down from a warning to plain
// tones, so the order of the list, not its color, says what is worst.
const ACTION_STYLE: Record<ReputationActionTone, { label: string; tagType: LemonTagType; border: string }> = {
    blocking: { label: 'Sending paused', tagType: 'danger', border: 'border-l-danger' },
    high: { label: 'Fix now', tagType: 'warning', border: 'border-l-warning' },
    medium: { label: 'Needs attention', tagType: 'default', border: 'border-l-transparent' },
    low: { label: 'Worth a look', tagType: 'muted', border: 'border-l-transparent' },
}

export function actionStyle(action: Pick<ReputationAction, 'blocksSending' | 'severity'>): {
    label: string
    tagType: LemonTagType
    border: string
} {
    return ACTION_STYLE[action.blocksSending ? 'blocking' : action.severity]
}

/** An unnamed workflow shows its id, so the action list and the table name it the same way. */
export function workflowName(workflow: WorkflowEmailSendingRatesApi): string {
    return workflow.hog_flow_name || workflow.hog_flow_id
}

// Reserved words like "Warning" / "Critical" belong to the tenant-level AWS verdict. These coarser
// buckets are a triage aid for spotting which workflows pull the project's numbers the wrong way.
//
// The "high" lines match the day-long rates at which PostHog pauses a workflow's email
// (WORKFLOW_EMAIL_AUTO_PAUSE_BOUNCE_RATE_24H and WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_24H), so
// the list never tells someone they have room above a rate that already pauses a workflow. The
// "elevated" lines sit below them as early warnings. SES's own lines are higher: its dashboard
// reviews at 5% bounce / 0.1% complaint, and tenant enforcement (the Standard reputation policy)
// raises high-severity findings at >15% bounce / >1% complaint. Sources:
// https://docs.aws.amazon.com/ses/latest/dg/reputationdashboardmessages.html (dashboard lines)
// https://aws.amazon.com/blogs/messaging-and-targeting/implement-tenants-in-your-amazon-ses-environment-part-3-implementation-guide/ (tenant policy lines)
export const RATE_THRESHOLDS = {
    bounce: { elevated: 0.03, high: 0.05 },
    complaint: { elevated: 0.001, high: 0.003 },
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

export type ExceededLevel = Exclude<RateLevel, 'healthy'>

export function rateOf(rates: { bounce_rate: number; complaint_rate: number }, kind: RateKind): number {
    return kind === 'bounce' ? rates.bounce_rate : rates.complaint_rate
}

/** The line a rate is over, or null when it is healthy or has too little volume to judge. */
export function exceededLevel(rate: number, kind: RateKind, volume: number): ExceededLevel | null {
    if (volume < minimumVolumeToClassify(kind)) {
        return null
    }
    const level = classifyRate(rate, kind)
    return level === 'healthy' ? null : level
}

/** True when the email provider stopped all of the project's sending, whatever its findings say. */
export function isSendingStopped(aws: AwsTenantReputationApi | null): boolean {
    return !!aws && (aws.sending_status === 'DISABLED' || aws.health === 'suspended')
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
