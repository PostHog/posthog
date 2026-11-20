import { EMAIL_METRIC_INVOCATION_FILTERS, EmailMetricName } from '../../Workflows/workflowMetricsSummaryLogic'
import { emailMetricSendFilters } from './emailMetricSends'

const NOW = '2026-03-15T12:00:00.000Z'

describe('emailMetricSendFilters', () => {
    beforeEach(() => jest.useFakeTimers({ now: new Date(NOW) }))
    afterEach(() => jest.useRealTimers())

    it('lists the sends behind every metric the metrics summary offers as a click', () => {
        const range = { dateFrom: '2026-03-14T00:00:00.000Z', dateTo: NOW }
        const dates = { date_from: range.dateFrom, date_to: NOW }
        const metrics = Object.keys(EMAIL_METRIC_INVOCATION_FILTERS) as EmailMetricName[]

        expect(Object.fromEntries(metrics.map((metric) => [metric, emailMetricSendFilters(metric, range)]))).toEqual({
            email_bounced: { status: 'bounced', ...dates },
            email_bounced_hard: { status: 'bounced', reason: 'hard', ...dates },
            email_bounced_transient: { status: 'bounced', reason: 'soft', ...dates },
            email_bounced_undetermined: { status: 'bounced', reason: 'unknown', ...dates },
            email_bounce_prevented: { status: 'failed', reason: 'recipient_unreachable', ...dates },
            email_missing_recipient: { status: 'failed', reason: 'missing_recipient', ...dates },
            message_frequency_capped: { status: 'failed', reason: 'frequency_capped', ...dates },
            email_blocked: { status: 'complained', ...dates },
            email_suspended: { status: 'failed', reason: 'sending_suspended', ...dates },
            email_paused: { status: 'failed', reason: 'sending_paused', ...dates },
        })
    })

    it('lists the sends of the days the log keeps when the metrics range reaches further back', () => {
        expect(
            emailMetricSendFilters('email_bounced_hard', { dateFrom: '2025-12-15T00:00:00.000Z', dateTo: NOW })
        ).toEqual({ status: 'bounced', reason: 'hard', date_from: '2026-02-13T12:00:00.000Z', date_to: NOW })
    })

    it('lists nothing for an open, which the log keeps no filter for', () => {
        expect(emailMetricSendFilters('email_opened', { dateFrom: '2026-03-14T00:00:00.000Z', dateTo: NOW })).toBeNull()
    })
})
