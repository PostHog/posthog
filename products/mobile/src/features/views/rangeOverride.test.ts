import type { RangeChoice } from '@/model/views'

import { compareQuery, overrideForTile, rangeOverride } from './rangeOverride'
import { customRange } from './rangePresets'

describe('range overrides', () => {
    test.each<[string, RangeChoice, string]>([
        ['a preset without an end', { kind: 'preset', key: '7d' }, '{"date_from":"-7d","date_to":null}'],
        ['a preset with an end', { kind: 'preset', key: 'yesterday' }, '{"date_from":"-1dStart","date_to":"-1dEnd"}'],
        [
            'a custom range picked end first',
            customRange('2026-09-15', '2026-09-01'),
            '{"date_from":"2026-09-01","date_to":"2026-09-15","explicitDate":false}',
        ],
    ])('always sends date_to for %s', (_name, choice, json) => {
        expect(JSON.stringify(rangeOverride(choice))).toBe(json)
    })

    test('reads a SQL tile without the filters placeholder without the override', () => {
        const override = rangeOverride({ kind: 'preset', key: '30d' })

        expect(overrideForTile({ ignoresRangeOverride: true }, override)).toBeNull()
        expect(overrideForTile({ ignoresRangeOverride: false }, override)).toBe(override)
    })

    test('builds the compare query from the response source, and none for all time', () => {
        const query = { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', dateRange: { date_from: '-30d' } } }

        expect(compareQuery(query, { kind: 'preset', key: '7d' })).toEqual({
            kind: 'TrendsQuery',
            dateRange: { date_from: '-7d', date_to: null },
            compareFilter: { compare: true },
        })
        expect(compareQuery(query, { kind: 'preset', key: 'all' })).toBeNull()
    })

    test.each(['HogQLQuery', 'RetentionQuery', 'FunnelsQuery', 'PathsQuery'])(
        'leaves comparison unavailable for %s',
        (kind) => {
            expect(compareQuery({ kind: 'InsightVizNode', source: { kind } }, null)).toBeNull()
        }
    )

    test('can explicitly turn off a saved trends comparison', () => {
        const query = {
            kind: 'InsightVizNode',
            source: { kind: 'TrendsQuery', dateRange: { date_from: '-7d' }, compareFilter: { compare: true } },
        }
        expect(compareQuery(query, null, false)).toMatchObject({
            kind: 'TrendsQuery',
            dateRange: { date_from: '-7d' },
            compareFilter: { compare: false },
        })
    })
})
