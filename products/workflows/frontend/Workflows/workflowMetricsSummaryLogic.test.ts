import { AppMetricsTimeSeriesResponse } from 'lib/components/AppMetrics/appMetricsLogic'

import type { IntegrationType } from '~/types'

import {
    type EmailMetric,
    buildEmailMetricInvocationSearchParams,
    buildEmailMetricRows,
    getEmailActionProvider,
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

const emailAction = (integrationId?: number): { config: { inputs: Record<string, { value?: any }> } } => ({
    config: { inputs: { email: { value: integrationId != null ? { from: { integrationId } } : {} } } },
})

const integration = (id: number, provider?: string): IntegrationType =>
    ({ id, kind: 'email', config: provider ? { provider } : {} }) as IntegrationType

describe('getEmailActionProvider', () => {
    it.each([
        {
            name: 'resolves an SMTP sender',
            action: emailAction(1),
            integrations: [integration(1, 'smtp')],
            expected: 'smtp',
        },
        {
            name: 'defaults senders created before the provider field to ses',
            action: emailAction(1),
            integrations: [integration(1)],
            expected: 'ses',
        },
        {
            name: 'returns null when the sender integration no longer exists',
            action: emailAction(99),
            integrations: [integration(1, 'smtp')],
            expected: null,
        },
        {
            name: 'returns null while integrations are still loading',
            action: emailAction(1),
            integrations: null,
            expected: null,
        },
        {
            name: 'returns null when no sender is picked',
            action: emailAction(),
            integrations: [integration(1, 'smtp')],
            expected: null,
        },
    ])('$name', ({ action, integrations, expected }) => {
        expect(getEmailActionProvider(action, integrations)).toEqual(expected)
    })
})

describe('buildEmailMetricRows', () => {
    const actions = [{ id: 'a1', name: 'Welcome email' }]

    // The delivered fallback (sent - bounced - blocked) must never run for SMTP senders: with no
    // delivery feedback it would report every relay-accepted send as delivered.
    it.each([
        {
            name: 'SMTP: no fabricated delivered count, delivery feedback flagged unsupported',
            totals: { a1: { email_sent: 100, email_opened: 4 } },
            providers: { a1: 'smtp' },
            expected: { delivered: 0, deliveryFeedbackSupported: false },
        },
        {
            name: 'SES: delivered fallback applies when the metric is absent',
            totals: { a1: { email_sent: 100, email_bounced: 5, email_blocked: 3 } },
            providers: { a1: 'ses' },
            expected: { delivered: 92, deliveryFeedbackSupported: true },
        },
        {
            name: 'SES: an explicit delivered total wins over the fallback',
            totals: { a1: { email_sent: 100, email_delivered: 42 } },
            providers: { a1: 'ses' },
            expected: { delivered: 42, deliveryFeedbackSupported: true },
        },
        {
            name: 'unresolved provider fails open to the SES behavior',
            totals: { a1: { email_sent: 10 } },
            providers: { a1: null },
            expected: { delivered: 10, deliveryFeedbackSupported: true },
        },
    ])('$name', ({ totals, providers, expected }) => {
        const [row] = buildEmailMetricRows(actions, totals, providers)
        expect(row).toMatchObject({ id: 'a1', email: 'Welcome email', sent: totals.a1.email_sent, ...expected })
    })
})
