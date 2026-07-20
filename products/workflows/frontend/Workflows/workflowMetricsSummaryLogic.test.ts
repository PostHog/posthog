import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'

import {
    type EmailMetric,
    buildEmailMetricInvocationSearchParams,
    buildEmailMetricRows,
    buildPushMetricRows,
    channelSentLabel,
    detectMessagingChannels,
    subtractSeries,
    withDisplayName,
} from './workflowMetricsSummaryLogic'

const series = (labels: string[], ...namedValues: [string, number[]][]): AppMetricsTimeSeriesResponse => ({
    labels,
    series: namedValues.map(([name, values]) => ({ name, values })),
})

describe('withDisplayName', () => {
    it.each([
        {
            name: 'returns null for null input',
            input: null,
            displayName: 'Custom',
            expected: null,
        },
        {
            name: 'replaces name on single series',
            input: series(['day1', 'day2'], ['original', [1, 2]]),
            displayName: 'Renamed',
            expected: series(['day1', 'day2'], ['Renamed', [1, 2]]),
        },
        {
            name: 'replaces name on multiple series',
            input: series(['day1'], ['a', [1]], ['b', [2]]),
            displayName: 'All same',
            expected: series(['day1'], ['All same', [1]], ['All same', [2]]),
        },
    ])('$name', ({ input, displayName, expected }) => {
        expect(withDisplayName(input, displayName)).toEqual(expected)
    })
})

describe('subtractSeries', () => {
    it.each([
        {
            name: 'both null returns null',
            minuend: null,
            subtrahend: null,
            displayName: 'Result',
            expected: null,
        },
        {
            name: 'null subtrahend uses zeros',
            minuend: series(['d1', 'd2'], ['sent', [5, 10]]),
            subtrahend: null,
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [5, 10]]),
        },
        {
            name: 'null minuend uses zeros',
            minuend: null,
            subtrahend: series(['d1', 'd2'], ['failed', [3, 7]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [0, 0]]),
        },
        {
            name: 'subtracts values element-wise',
            minuend: series(['d1', 'd2', 'd3'], ['sent', [10, 20, 30]]),
            subtrahend: series(['d1', 'd2', 'd3'], ['failed', [2, 5, 10]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2', 'd3'], ['Delivered', [8, 15, 20]]),
        },
        {
            name: 'clamps negative results to zero',
            minuend: series(['d1', 'd2'], ['sent', [1, 0]]),
            subtrahend: series(['d1', 'd2'], ['failed', [5, 3]]),
            displayName: 'Delivered',
            expected: series(['d1', 'd2'], ['Delivered', [0, 0]]),
        },
    ])('$name', ({ minuend, subtrahend, displayName, expected }) => {
        expect(subtractSeries(minuend, subtrahend, displayName)).toEqual(expected)
    })
})

describe('buildEmailMetricInvocationSearchParams', () => {
    const dateFrom = '2026-07-01T00:00:00.000Z'
    const dateTo = '2026-07-13T00:00:00.000Z'

    // Each metric drills into the Invocations tab via the unified search box (`inv_search`), narrowed
    // to the level that distinguishes it: bounced/blocked at WARN/ERROR, bounce prevented
    // ("Skipping send") at INFO.
    it.each<[EmailMetric, Record<string, string>]>([
        [
            'email_bounced',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'bounce', inv_log_levels: 'WARN,ERROR' },
        ],
        [
            'email_blocked',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Complaint', inv_log_levels: 'WARN,ERROR' },
        ],
        [
            'email_bounce_prevented',
            { inv_date_from: dateFrom, inv_date_to: dateTo, inv_search: 'Skipping send', inv_log_levels: 'INFO' },
        ],
    ])('maps %s to the expected Invocations-tab params', (metricKey, expected) => {
        expect(buildEmailMetricInvocationSearchParams(metricKey, dateFrom, dateTo)).toEqual(expected)
    })

    it.each<EmailMetric>(['email_sent', 'email_delivered', 'email_opened', 'email_failed'])(
        'returns null for the non-drillable metric %s',
        (metricKey) => {
            expect(buildEmailMetricInvocationSearchParams(metricKey, dateFrom, dateTo)).toBeNull()
        }
    )
})

describe('detectMessagingChannels', () => {
    // Only the `*_sent` series flip a channel on — this guards the exact metric names the tile keys off.
    it.each([
        { name: 'no trends', input: null, expected: { hasEmail: false, hasPush: false } },
        {
            name: 'email only',
            input: series(['d1'], ['email_sent', [3]]),
            expected: { hasEmail: true, hasPush: false },
        },
        { name: 'push only', input: series(['d1'], ['push_sent', [2]]), expected: { hasEmail: false, hasPush: true } },
        {
            name: 'both channels',
            input: series(['d1'], ['email_sent', [3]], ['push_sent', [2]]),
            expected: { hasEmail: true, hasPush: true },
        },
        {
            name: 'ignores non-sent series',
            input: series(['d1'], ['email_delivered', [3]], ['push_skipped', [1]]),
            expected: { hasEmail: false, hasPush: false },
        },
    ])('$name', ({ input, expected }) => {
        expect(detectMessagingChannels(input)).toEqual(expected)
    })
})

describe('channelSentLabel', () => {
    it.each([
        [{ hasEmail: true, hasPush: true }, 'Messages'],
        [{ hasEmail: false, hasPush: true }, 'Push notifications'],
        [{ hasEmail: true, hasPush: false }, 'Emails'],
        [{ hasEmail: false, hasPush: false }, 'Emails'],
    ])('%o -> %s', (channels, expected) => {
        expect(channelSentLabel(channels)).toBe(expected)
    })
})

describe('buildEmailMetricRows', () => {
    it('maps each metric key onto the row, preferring the reported email_delivered', () => {
        const rows = buildEmailMetricRows([{ id: 'a1', name: 'Welcome email' }], {
            a1: {
                email_sent: 100,
                email_delivered: 85, // reported value wins over the derived sent - bounced - blocked (= 90)
                email_opened: 40,
                email_link_clicked: 12,
                email_bounced: 6,
                email_bounce_prevented: 2,
                email_blocked: 4,
            },
        })
        expect(rows).toEqual([
            {
                id: 'a1',
                email: 'Welcome email',
                sent: 100,
                delivered: 85,
                opened: 40,
                linkClicked: 12,
                bounced: 6,
                bouncePrevented: 2,
                blocked: 4,
            },
        ])
    })

    // delivered falls back to sent - bounced - blocked (clamped at 0) when it wasn't collected.
    it.each<{ totals: Partial<Record<EmailMetric, number>>; delivered: number }>([
        { totals: { email_sent: 10, email_bounced: 3, email_blocked: 2 }, delivered: 5 },
        { totals: { email_sent: 1, email_bounced: 5 }, delivered: 0 },
        { totals: {}, delivered: 0 },
    ])('derives delivered=$delivered when email_delivered is absent', ({ totals, delivered }) => {
        expect(buildEmailMetricRows([{ id: 'a1', name: 'E' }], { a1: totals })[0].delivered).toBe(delivered)
    })
})

describe('buildPushMetricRows', () => {
    it('maps sent/skipped/failed per action and defaults missing totals to 0', () => {
        const rows = buildPushMetricRows(
            [
                { id: 'p1', name: 'Reminder' },
                { id: 'p2', name: 'Promo' },
            ],
            { p1: { push_sent: 50, push_skipped: 20, push_failed: 3 } }
        )
        expect(rows).toEqual([
            { id: 'p1', push: 'Reminder', sent: 50, skipped: 20, failed: 3 },
            { id: 'p2', push: 'Promo', sent: 0, skipped: 0, failed: 0 },
        ])
    })
})
