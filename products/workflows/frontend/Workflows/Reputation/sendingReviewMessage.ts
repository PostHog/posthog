import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { AwsTenantFindingApi, EmailSendingRatesApi } from 'products/workflows/frontend/generated/api.schemas'

import { type SuspensionCause, FINDING_TYPE_LABELS, formatRate } from './emailReputation'

/**
 * The support message the "Request a review" button opens with. It carries the reputation state the
 * reviewer would otherwise have to ask for, and it ends on an open line so the customer says what
 * they changed — which is the part no query can answer.
 */
export function buildSendingReviewMessage({
    cause,
    reason,
    reputation,
    findings,
}: {
    cause: SuspensionCause
    reason: string
    reputation: EmailSendingRatesApi | null
    findings: readonly AwsTenantFindingApi[]
}): string {
    const lines = [
        'Please review workflow email sending for this project.',
        '',
        `Sending status: ${cause === 'staff' ? 'suspended by PostHog' : 'paused by the email provider'}`,
    ]
    if (reason) {
        lines.push(`Reason given: ${reason}`)
    }
    if (reputation) {
        lines.push(
            `Bounce rate (last 30 days): ${formatRate(reputation.bounce_rate)}`,
            `Spam complaint rate (last 30 days): ${formatRate(reputation.complaint_rate)}`,
            `Emails sent (last 30 days): ${humanFriendlyNumber(reputation.emails_sent)}`
        )
    }
    if (findings.length > 0) {
        const described = findings.map(
            (finding) =>
                `${FINDING_TYPE_LABELS[finding.finding_type] ?? finding.finding_type} (${finding.impact.toLowerCase()} impact)`
        )
        lines.push(`Open findings: ${described.join(', ')}`)
    }
    lines.push('', 'What I changed to fix the cause:')
    return lines.join('\n')
}
