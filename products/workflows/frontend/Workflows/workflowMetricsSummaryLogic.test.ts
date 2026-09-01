import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'

import {
    type EmailMetric,
    buildEmailMetricInvocationSearchParams,
    buildEmailMetricRows,
    buildPushMetricRows,
    channelSentLabel,
    detectMessagingChannels,
    parseEmailLinkTotals,
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
    // to the level that distinguishes it: bounced/marked-as-spam at WARN/ERROR, bounce prevented
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
        [{ hasEmail: true, hasPush: true }, 'Messages sent'],
        [{ hasEmail: false, hasPush: true }, 'Push notifications sent'],
        [{ hasEmail: true, hasPush: false }, 'Emails sent'],
        [{ hasEmail: false, hasPush: false }, 'Emails sent'],
    ])('%o -> %s', (channels, expected) => {
        expect(channelSentLabel(channels)).toBe(expected)
    })
})

describe('buildEmailMetricRows', () => {
    it('maps each metric key onto the row, preferring the reported email_delivered', () => {
        const rows = buildEmailMetricRows([{ id: 'a1', name: 'Welcome email' }], {
            a1: {
                email_sent: 100,
                email_delivered: 85, // reported value wins over the derived sent - bounced (= 94)
                email_opened: 40,
                email_link_clicked: 12,
                email_bounced: 6,
                email_bounce_prevented: 2,
                email_blocked: 4,
                email_untracked: 7,
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
                markedAsSpam: 4,
                untracked: 7,
                trackedSends: 93,
            },
        ])
    })

    it('keeps tracked sends positive when untracked sends outnumber deliveries', () => {
        const [row] = buildEmailMetricRows([{ id: 'a1', name: 'E' }], {
            a1: { email_sent: 100, email_delivered: 60, email_untracked: 90, email_bounced: 40 },
        })
        expect(row.trackedSends).toBe(10)
    })

    // delivered falls back to sent - bounced (clamped at 0) when it wasn't collected. Spam
    // complaints (email_blocked) are post-delivery reports, so they must not reduce delivered.
    it.each<{ totals: Partial<Record<EmailMetric, number>>; delivered: number }>([
        { totals: { email_sent: 10, email_bounced: 3, email_blocked: 2 }, delivered: 7 },
        { totals: { email_sent: 1, email_bounced: 5 }, delivered: 0 },
        { totals: {}, delivered: 0 },
    ])('derives delivered=$delivered when email_delivered is absent', ({ totals, delivered }) => {
        expect(buildEmailMetricRows([{ id: 'a1', name: 'E' }], { a1: totals })[0].delivered).toBe(delivered)
    })
})

describe('buildPushMetricRows', () => {
    it('maps sent/skipped/failed/opened per action and defaults missing totals to 0', () => {
        const rows = buildPushMetricRows(
            [
                { id: 'p1', name: 'Reminder' },
                { id: 'p2', name: 'Promo' },
            ],
            { p1: { push_sent: 50, push_skipped: 20, push_failed: 3, push_opened: 12 } }
        )
        expect(rows).toEqual([
            { id: 'p1', push: 'Reminder', sent: 50, skipped: 20, failed: 3, opened: 12 },
            { id: 'p2', push: 'Promo', sent: 0, skipped: 0, failed: 0, opened: 0 },
        ])
    })
})

describe('parseEmailLinkTotals', () => {
    const totals = (...instanceIds: [string, number][]): Record<string, { total: number; breakdowns: string[] }> =>
        Object.fromEntries(instanceIds.map(([id, total]) => [id, { total, breakdowns: [id] }]))

    it('groups links under their action, most clicked first', () => {
        expect(
            parseEmailLinkTotals(
                totals(
                    ['act-1|0|https://example.com/a', 3],
                    ['act-1|1|https://example.com/b', 9],
                    ['act-2|0|https://example.com/c', 1]
                )
            )
        ).toEqual({
            'act-1': [
                { linkIndex: '1', url: 'https://example.com/b', clicks: 9, truncated: false, duplicateUrl: false },
                { linkIndex: '0', url: 'https://example.com/a', clicks: 3, truncated: false, duplicateUrl: false },
            ],
            'act-2': [
                { linkIndex: '0', url: 'https://example.com/c', clicks: 1, truncated: false, duplicateUrl: false },
            ],
        })
    })

    it('keeps a url containing the field separator intact', () => {
        expect(parseEmailLinkTotals(totals(['act-1|0|https://example.com/a|b', 2]))['act-1']).toEqual([
            { linkIndex: '0', url: 'https://example.com/a|b', clicks: 2, truncated: false, duplicateUrl: false },
        ])
    })

    it('flags links that share a url within a step, so position can tell them apart', () => {
        const rows = parseEmailLinkTotals(
            totals(
                ['act-1|0|https://example.com/a', 4],
                ['act-1|7|https://example.com/a', 1],
                ['act-1|2|https://example.com/b', 2]
            )
        )['act-1']
        expect(rows.map((r) => [r.linkIndex, r.duplicateUrl])).toEqual([
            ['0', true],
            ['2', false],
            ['7', true],
        ])
    })

    it('flags a url stored at the length cap as truncated', () => {
        const longUrl = `https://example.com/${'x'.repeat(200)}`.slice(0, 200)
        expect(parseEmailLinkTotals(totals([`act-1|0|${longUrl}`, 1]))['act-1'][0].truncated).toBe(true)
    })

    it.each([
        ['an instance id with no link fields', 'act-1'],
        ['an instance id missing the url field', 'act-1|0'],
        ['an empty url', 'act-1|0|'],
    ])('ignores %s', (_name, instanceId) => {
        expect(parseEmailLinkTotals(totals([instanceId, 5]))).toEqual({})
    })
})
