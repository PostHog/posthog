import { EMAIL_METRIC_INVOCATION_FILTERS, EmailMetricName } from '../../Workflows/workflowMetricsSummaryLogic'
import { emailMetricSendFilters } from './emailMetricSends'

const NOW = '2026-03-15T12:00:00.000Z'

describe('emailMetricSendFilters', () => {
    beforeEach(() => jest.useFakeTimers({ now: new Date(NOW) }))
    afterEach(() => jest.useRealTimers())

    it.each(Object.keys(EMAIL_METRIC_INVOCATION_FILTERS) as EmailMetricName[])(
        'lists the sends behind %s, which the metrics summary offers as a click',
        (metric) => {
            expect(emailMetricSendFilters(metric, { dateFrom: '2026-03-14T00:00:00.000Z', dateTo: NOW })).toMatchObject(
                { date_from: '2026-03-14T00:00:00.000Z', date_to: NOW }
            )
        }
    )

    it('lists the sends of the days the log keeps when the metrics range reaches further back', () => {
        expect(
            emailMetricSendFilters('email_bounced_hard', { dateFrom: '2025-12-15T00:00:00.000Z', dateTo: NOW })
        ).toEqual({ status: 'bounced', reason: 'hard', date_from: '2026-02-13T12:00:00.000Z', date_to: NOW })
    })

    it('lists nothing for an open, which the log keeps no filter for', () => {
        expect(emailMetricSendFilters('email_opened', { dateFrom: '2026-03-14T00:00:00.000Z', dateTo: NOW })).toBeNull()
    })
})
