import type {
    AwsTenantFindingApi,
    TeamEmailReputationResponseApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { suspensionCauseFromResponse } from './emailReputation'
import { buildSendingReviewMessage } from './sendingReviewMessage'

describe('requesting a review of suspended workflow email', () => {
    const findings: AwsTenantFindingApi[] = [
        { finding_type: 'COMPLAINT', impact: 'HIGH', description: '', last_updated_at: null },
        { finding_type: 'DKIM', impact: 'LOW', description: 'DKIM1', last_updated_at: null },
    ]

    it('carries the reputation state a reviewer would otherwise have to ask for', () => {
        const message = buildSendingReviewMessage({
            cause: 'provider',
            reason: '',
            reputation: { bounce_rate: 0.0123, complaint_rate: 0.0004, emails_sent: 12345 },
            findings,
        })

        expect(message).toContain('Sending status: paused by the email provider')
        expect(message).toContain('Bounce rate (last 30 days): 1.23%')
        expect(message).toContain('Spam complaint rate (last 30 days): 0.04%')
        expect(message).toContain('Emails sent (last 30 days): 12,345')
        expect(message).toContain('Open findings: Spam complaints (high impact), DKIM setup (low impact)')
        expect(message.endsWith('What I changed to fix the cause:')).toBe(true)
    })

    it('names the staff reason and omits rates a project without recent sends has none of', () => {
        const message = buildSendingReviewMessage({
            cause: 'staff',
            reason: 'Hard bounce rate above 5%',
            reputation: null,
            findings: [],
        })

        expect(message).toContain('Sending status: suspended by PostHog')
        expect(message).toContain('Reason given: Hard bounce rate above 5%')
        expect(message).not.toContain('Bounce rate (last 30 days)')
        expect(message).not.toContain('Open findings')
    })

    it.each([
        { name: 'staff suspension alone', staffSuspended: true, sendingStatus: 'ENABLED', expected: 'staff' },
        { name: 'provider pause alone', staffSuspended: false, sendingStatus: 'DISABLED', expected: 'provider' },
        // A staff suspension outlives the provider one, so reporting "provider" would send the
        // customer chasing rates that cannot unblock them.
        { name: 'both at once', staffSuspended: true, sendingStatus: 'DISABLED', expected: 'staff' },
        { name: 'neither', staffSuspended: false, sendingStatus: 'ENABLED', expected: null },
    ])('reports $name as $expected', ({ staffSuspended, sendingStatus, expected }) => {
        const response = {
            email_sending_suspended: staffSuspended,
            aws: { health: 'healthy', sending_status: sendingStatus, findings: [] },
        } as unknown as TeamEmailReputationResponseApi

        expect(suspensionCauseFromResponse(response)).toBe(expected)
    })
})
