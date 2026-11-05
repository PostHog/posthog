import type { InsightApi } from '@/api/insights'
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
