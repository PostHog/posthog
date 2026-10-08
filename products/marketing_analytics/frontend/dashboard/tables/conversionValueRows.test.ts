import { BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { TrendResult } from '~/types'

import { conversionValueRows } from './conversionValueRows'

const result = (
    order: number,
    breakdownValue: string,
    aggregatedValue: number,
    compareLabel?: 'current' | 'previous'
): TrendResult =>
    ({
        action: { order },
        breakdown_value: breakdownValue,
        aggregated_value: aggregatedValue,
        compare_label: compareLabel ?? 'current',
    }) as unknown as TrendResult

describe('conversionValueRows', () => {
    it('pairs each breakdown with its previous period, by series order', () => {
        const rows = conversionValueRows([
            result(0, 'Paid Search', 4000),
            result(0, 'Paid Search', 3000, 'previous'),
            result(1, 'Paid Search', 80),
            result(1, 'Paid Search', 75, 'previous'),
        ])

        expect(rows.get('Paid Search')).toEqual({ total: [4000, 3000], average: [80, 75] })
    })

    it('leaves the previous period null when the breakdown is new', () => {
        const rows = conversionValueRows([result(0, 'Email', 900), result(1, 'Email', 45)])

        expect(rows.get('Email')).toEqual({ total: [900, null], average: [45, null] })
    })

    // The stats table reports an untagged visit as SQL NULL, which webStatsRows reads as ''. If
    // these two did not agree, that row's value cells would silently stay empty.
    it('keys the trends null sentinel the way the stats table keys an untagged row', () => {
        const rows = conversionValueRows([result(0, BREAKDOWN_NULL_STRING_LABEL, 120)])

        expect(rows.has(BREAKDOWN_NULL_STRING_LABEL)).toBe(false)
        expect(rows.get('')).toEqual({ total: [120, null] })
    })

    // The fold is a total over values the stats table lists one by one, so merging it would
    // attribute the whole tail to whichever row happened to carry that name.
    it('drops the folded "other" row', () => {
        const rows = conversionValueRows([result(0, BREAKDOWN_OTHER_STRING_LABEL, 5000), result(0, 'Direct', 100)])

        expect([...rows.keys()]).toEqual(['Direct'])
    })

    it('returns nothing for an absent response', () => {
        expect(conversionValueRows(undefined).size).toBe(0)
    })
})
