import type { InsightApi } from '@/api/insights'
import { isCompleteShortcutPage, SHORTCUT_PAGE_SIZE } from '@/api/shortcuts'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
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
        expect(catalog.pins.map(({ displayMode: _mode, ...pin }) => pin)).toEqual([
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
            expect.objectContaining({ id: 's-funnel', eligible: true, reason: null }),
            expect.objectContaining({ id: 's-sql', eligible: true, reason: null }),
            expect.objectContaining({ id: 's-browsers', eligible: true, number: false, chart: false }),
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

test('keeps dashboard tile values and display modes scoped to each pin', () => {
    const query = { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery' }, display: 'BoldNumber' }
    const pins = [10, 20].map((id) =>
        pin(`pin-${id}`, 'dashboard', String(id), `Dashboard ${id}`, { mode: 'number', insightId: 101 })
    )
    const metadata = new Map(
        pins.map((pin, index) => {
            const response: InsightApi = {
                id: 101,
                short_id: 'same-insight',
                name: 'Example',
                derived_name: null,
                query,
                result: [[index + 1]],
                columns: ['value'],
                types: [['value', 'UInt64']],
                last_refresh: null,
                cache_target_age: null,
                next_allowed_client_refresh: null,
            }
            return [
                pin.shortcutId,
                {
                    insightId: 101,
                    shortId: 'same-insight',
                    name: 'Example',
                    query,
                    snapshot: insightSnapshot(response, undefined, { readAt: 1000, serverNow: 1000 }),
                },
            ] as const
        })
    )
    const catalog = buildCatalog(pins, metadata, { host: 'https://example.com', projectId: 1, projectName: 'Example' })
    expect(
        catalog.pins.map((pin) => [
            pin.dashboardId,
            pin.eligible,
            pin.displayMode,
            pin.shortId,
            pin.snapshot?.valueText,
        ])
    ).toEqual([
        [10, true, 'number', 'same-insight', '1'],
        [20, true, 'number', 'same-insight', '2'],
    ])
    const selected = buildCatalog(
        pins,
        metadata,
        { host: 'https://example.com', projectId: 1, projectName: 'Example' },
        new Set(['pin-10'])
    )
    expect(selected.pins.map((pin) => pin.snapshot?.valueText)).toEqual(['1', undefined])
    expect(selected.pins.map((pin) => pin.eligible)).toEqual([true, true])
})

test('accepts a full final pin page and keeps every visible pin', () => {
    const results = Array.from({ length: SHORTCUT_PAGE_SIZE }, (_, index) => ({
        id: `pin-${index}`,
        path: `Example ${index}`,
        type: 'insight',
        ref: `insight-${index}`,
        href: null,
        order: index,
        created_at: '',
    }))
    expect(isCompleteShortcutPage({ count: results.length, next: null, results })).toBe(true)
    expect(isCompleteShortcutPage({ count: results.length + 1, next: 'https://example.com/next', results })).toBe(false)
    const pins = results.map((result) => pin(result.id, 'insight', result.ref, result.path))
    const catalog = buildCatalog(pins, new Map(), { host: 'https://example.com', projectId: 1, projectName: 'Example' })
    expect(catalog.pins.map((item) => item.id)).toEqual(results.map((item) => item.id))
})
