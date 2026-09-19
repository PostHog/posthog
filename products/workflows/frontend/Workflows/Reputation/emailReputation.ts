import { percentage } from 'lib/utils/numbers'

import type { TeamEmailReputationResponseApi } from 'products/workflows/frontend/generated/api.schemas'

export type SuspensionCause = 'staff' | 'provider'

// Thresholds mirror SES's account-level reputation dashboard warning lines (bounce: 5% review /
// 10% pause; complaint: 0.1% review / 0.5% pause), deliberately conservative early warnings.
// Actual tenant enforcement (the Standard reputation policy) pauses much higher — high-severity
// findings at >15% bounce / >1% complaint — so a "high" rate here means "fix this now", not
// "sending is about to stop". Sources:
// https://docs.aws.amazon.com/ses/latest/dg/reputationdashboardmessages.html (dashboard lines)
// https://aws.amazon.com/blogs/messaging-and-targeting/implement-tenants-in-your-amazon-ses-environment-part-3-implementation-guide/ (tenant policy lines)
export const RATE_THRESHOLDS = {
    bounce: { elevated: 0.03, high: 0.05 },
    complaint: { elevated: 0.001, high: 0.005 },
} as const

export const FINDING_TYPE_LABELS: Record<string, string> = {
    DKIM: 'DKIM setup',
    DMARC: 'DMARC setup',
    SPF: 'SPF setup',
    BIMI: 'BIMI setup',
    COMPLAINT: 'Spam complaints',
    BOUNCE: 'Bounces',
    FEEDBACK_3P: 'Third-party feedback',
    IP_LISTING: 'Blocklist listing',
}

export function formatRate(rate: number): string {
    return percentage(rate, 2, true)
}

/**
 * Why this project's workflow email stopped, or null while it is sending. Staff wins when both
 * hold, mirroring the send path's own precedence (getEmailSendingSuspension): the cause a customer
 * cannot clear by fixing rates is the one to explain.
 */
export function suspensionCauseFromResponse(response: TeamEmailReputationResponseApi | null): SuspensionCause | null {
    if (response?.email_sending_suspended) {
        return 'staff'
    }
    return response?.aws?.sending_status === 'DISABLED' ? 'provider' : null
}
