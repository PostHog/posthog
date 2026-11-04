import type { PinDisplay, PinKind, PinView } from '@/model/views'

import { buildCatalog, type WidgetPinInsight } from './chartWidgetCatalog'

function pin(shortcutId: string, kind: PinKind, ref: string, name: string, display: PinDisplay = { mode: 'row' }) {
    return {
        kind,
        ref,
        href: null,
        name,
        shortcutId,
        shortcutIds: [shortcutId],
        serverOrder: 0,
        rank: null,
        display,
    } satisfies PinView
}

function trends(series: number, display: string, breakdown = false): unknown {
    return {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: Array.from({ length: series }, () => ({ kind: 'EventsNode', event: '$pageview' })),
            trendsFilter: { display },
            ...(breakdown ? { breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' } } : {}),
        },
    }
}

function insight(insightId: number, shortId: string, name: string, query: unknown): WidgetPinInsight {
    return { insightId, shortId, name, query }
}

describe('buildCatalog', () => {
    it('lists every pin in Views order with what the widget can show and why not', () => {
        const pins = [
            pin('s-signups', 'insight', 'sig1', 'Signups'),
            pin('s-kpis', 'dashboard', '12', 'Product KPIs', {
                mode: 'chart',
                tileId: 3,
                insightId: 456,
                insightShortId: 'dau1',
            }),
            pin('s-board', 'dashboard', '13', 'Growth'),
            pin('s-funnel', 'insight', 'fun1', 'Checkout funnel'),
            pin('s-sql', 'insight', 'sql1', 'Revenue by plan'),
            pin('s-browsers', 'insight', 'brw1', 'Browsers'),
            pin('s-steps', 'insight', 'stp1', 'Steps'),
            pin('s-unread', 'insight', 'new1', 'Fresh pin'),
            pin('s-gone', 'insight', 'old1', 'Removed'),
        ]
        const metadata = new Map<string, WidgetPinInsight | null>([
            ['sig1', insight(123, 'sig1', 'Signups', trends(1, 'ActionsLineGraph'))],
            ['dau1', insight(456, 'dau1', 'Daily active users', trends(1, 'ActionsBar'))],
            [
                'fun1',
                insight(789, 'fun1', 'Checkout funnel', { kind: 'InsightVizNode', source: { kind: 'FunnelsQuery' } }),
            ],
            [
                'sql1',
                insight(790, 'sql1', 'Revenue by plan', {
                    kind: 'DataVisualizationNode',
                    source: { kind: 'HogQLQuery' },
                }),
            ],
            ['brw1', insight(791, 'brw1', 'Browsers', trends(1, 'ActionsPie', true))],
            ['stp1', insight(792, 'stp1', 'Steps', trends(3, 'ActionsLineGraph'))],
            ['old1', null],
        ])

        const catalog = buildCatalog(pins, metadata, {
            host: 'https://us.posthog.com',
            projectId: 2,
            projectName: 'Example project',
        })

        expect(catalog).toMatchObject({ version: 1, host: 'https://us.posthog.com', projectId: 2 })
        expect(catalog.pins).toEqual([
            {
                id: 's-signups',
                kind: 'insight',
                name: 'Signups',
                subtitle: 'Insight',
                insightId: 123,
                shortId: 'sig1',
                dashboardId: null,
                eligible: true,
                number: true,
                chart: true,
                reason: null,
            },
            {
                id: 's-kpis',
                kind: 'dashboard',
                name: 'Product KPIs',
                subtitle: 'Product KPIs · Daily active users',
                insightId: 456,
                shortId: 'dau1',
                dashboardId: 12,
                eligible: true,
                number: true,
                chart: true,
                reason: null,
            },
            expect.objectContaining({
                id: 's-board',
                subtitle: 'Dashboard',
                insightId: null,
                shortId: null,
                dashboardId: 13,
                eligible: false,
                reason: 'Choose a tile in Views first',
            }),
            expect.objectContaining({ id: 's-funnel', eligible: false, reason: 'Not a chart over time' }),
            expect.objectContaining({ id: 's-sql', eligible: false, reason: 'Not supported on the widget yet' }),
            expect.objectContaining({ id: 's-browsers', eligible: false, number: false, chart: false }),
            expect.objectContaining({ id: 's-steps', eligible: true, number: false, chart: true }),
            expect.objectContaining({
                id: 's-unread',
                insightId: null,
                eligible: false,
                reason: 'Open it in Views first',
            }),
            expect.objectContaining({ id: 's-gone', eligible: false, reason: "Couldn't find this insight" }),
        ])
    })
})
