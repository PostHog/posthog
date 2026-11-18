import type { LemonTagType } from '@posthog/lemon-ui'

// Per-workflow rate classification. Reserved words like "Warning" / "Critical" belong to the
// tenant-level AWS verdict (the reputation page's HEALTH_TAG) — these coarser buckets are just a triage aid for
// spotting which workflows are pulling the project's numbers in the wrong direction.
//
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

export type RateLevel = 'healthy' | 'elevated' | 'high'

// Below this much volume one event on its own clears the elevated line, so a tag would be
// reporting noise: one bounce in 20 sends reads as 5%.
export function minimumVolumeToClassify(kind: 'bounce' | 'complaint'): number {
    return Math.ceil(1 / RATE_THRESHOLDS[kind].elevated)
}

export function classifyRate(rate: number, kind: 'bounce' | 'complaint'): RateLevel {
    const thresholds = RATE_THRESHOLDS[kind]
    if (rate >= thresholds.high) {
        return 'high'
    }
    if (rate >= thresholds.elevated) {
        return 'elevated'
    }
    return 'healthy'
}

export const RATE_LEVEL_TAG: Record<RateLevel, { label: string; type: LemonTagType }> = {
    healthy: { label: 'Healthy', type: 'success' },
    elevated: { label: 'Elevated', type: 'warning' },
    high: { label: 'High', type: 'danger' },
}
