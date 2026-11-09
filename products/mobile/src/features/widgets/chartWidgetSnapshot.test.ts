import type { InsightApi } from '@/api/insights'
import { demoInsightResponse } from '@/demo/views'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'

import fixtures from '../../../modules/chart-widget/fixtures/insights.json'
import { widgetSnapshot } from './chartWidgetSnapshot'

// The native parser checks consume the same invented responses, so numeric and display semantics stay aligned.
describe('widget snapshots use the Views representation', () => {
    test.each(fixtures)('$name', ({ response, expected }) => {
        const at = Date.parse('2026-11-02T12:00:00Z')
        const source = insightSnapshot(response as InsightApi, undefined, { readAt: at, serverNow: at })
        const snapshot = widgetSnapshot('pin-example', source, 'row')
        if ('appSnapshot' in expected && !expected.appSnapshot) {
            expect(snapshot).toBeNull()
            return
        }
        expect(snapshot).not.toBeNull()
        expect(snapshot?.display).toBe(expected.display)
        for (const field of ['chartValueText', 'axisLowText', 'axisHighText'] as const) {
            if (field in expected) expect(snapshot?.[field]).toBe(expected[field])
        }
        if ('intervalLabel' in expected) expect(snapshot?.intervalLabel).toBe(expected.intervalLabel)
        if ('valueText' in expected) expect(snapshot?.valueText).toBe(expected.valueText)
        if ('firstRowValue' in expected) expect(snapshot?.rows[0]?.value).toBe(expected.firstRowValue)
        if (typeof expected.rowCount === 'number') expect(snapshot?.rows).toHaveLength(expected.rowCount)
        if (typeof expected.seriesCount === 'number') expect(snapshot?.series).toHaveLength(expected.seriesCount)
        if ('firstAt' in expected) expect(snapshot?.series[0]?.points[0]?.at).toBe(expected.firstAt)
        if ('firstValue' in expected) expect(snapshot?.series[0]?.points[0]?.value).toBe(expected.firstValue)
        if ('lastIsGap' in expected) expect(snapshot?.series[0]?.points.at(-1)?.value).toBeNull()
        if ('lastValue' in expected) expect(snapshot?.series[0]?.points.at(-1)?.value).toBe(expected.lastValue)
    })
})

test('number mode keeps a single-series category insight as a number', () => {
    const response = fixtures.find((fixture) => fixture.name === 'Trends breakdown')?.response
    if (!response) throw new Error('Missing trends fixture')
    const source = insightSnapshot(
        {
            ...response,
            query: {
                kind: 'InsightVizNode',
                source: {
                    kind: 'TrendsQuery',
                    series: [{ kind: 'EventsNode', event: 'example' }],
                    trendsFilter: { display: 'ActionsTable' },
                },
            },
            result: [{ label: 'Example', aggregated_value: 12 }],
        } as InsightApi,
        undefined,
        { readAt: 1000, serverNow: 1000 }
    )
    const snapshot = widgetSnapshot('example', source, 'number')
    expect(snapshot).toMatchObject({ display: 'number', valueText: '12', rows: [] })
})

test('formats only the compact rows retained by the widget', () => {
    const at = Date.now()
    const source = insightSnapshot(
        {
            id: 101,
            short_id: 'table1',
            name: 'Table',
            query: {
                kind: 'DataVisualizationNode',
                source: { kind: 'HogQLQuery', query: 'select example' },
                display: 'ActionsTable',
            },
            columns: ['label', 'value'],
            types: [
                ['label', 'String'],
                ['value', 'UInt64'],
            ],
            result: Array.from({ length: 50_000 }, (_, i) => [`Row ${i}`, i]),
            last_refresh: null,
            cache_target_age: null,
            next_allowed_client_refresh: null,
        } as InsightApi,
        undefined,
        { readAt: at, serverNow: at }
    )
    const row = source.sqlTable?.rows[12]
    if (!row) throw new Error('Missing SQL row')
    Object.defineProperty(row, 0, {
        get: () => {
            throw new Error('Formatted a discarded row')
        },
    })
    expect(widgetSnapshot('example', source, 'row')?.rows).toHaveLength(12)
})

// Widgets keep their existing row representation until their native snapshot format supports mixed axes.
test('keeps mixed-axis SQL values as formatted rows in home-screen widgets', () => {
    const at = Date.parse('2026-11-02T12:00:00Z')
    const response = demoInsightResponse({ shortId: 'demo-sql-revenue', dashboardRef: null, override: null }, at)
    if (!response) throw new Error('Missing SQL demo insight')
    const source = insightSnapshot(response, undefined, { readAt: at, serverNow: at })
    expect(source.capabilities.chart).toBe(true)
    const snapshot = widgetSnapshot('example', source, 'chart')
    expect(snapshot).toMatchObject({ display: 'rows', series: [] })
    expect(snapshot?.rows[1]?.label).toBe('Mar 2026')
    expect(snapshot?.rows[1]?.value).toContain('20.0%')
})
