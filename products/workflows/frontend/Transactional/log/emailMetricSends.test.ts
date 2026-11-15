import { emailMetricSendFilters } from './emailMetricSends'

describe('emailMetricSendFilters', () => {
    test.each([
        ['every bounce', 'email_bounced', { dateFrom: '-30d' }, { status: 'bounced', date_from: '-30d' }],
        [
            'a soft bounce',
            'email_bounced_transient',
            { dateFrom: '2026-03-01', dateTo: '2026-03-14' },
            { status: 'bounced', reason: 'soft', date_from: '2026-03-01', date_to: '2026-03-14' },
        ],
        ['a spam report', 'email_blocked', {}, { status: 'complained' }],
        ['a skip while paused', 'email_paused', {}, { status: 'failed', reason: 'sending_paused' }],
        ['an open, which the log keeps no filter for', 'email_opened', { dateFrom: '-7d' }, null],
    ] as const)('lists the sends behind %s', (_, metric, range, expected) => {
        expect(emailMetricSendFilters(metric, range)).toEqual(expected)
    })
})
