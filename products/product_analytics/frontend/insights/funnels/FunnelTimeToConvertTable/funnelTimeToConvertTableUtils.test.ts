import { HistogramGraphDatum } from '~/types'

import { buildTimeToConvertCompareRows } from './funnelTimeToConvertTableUtils'

const datum = (id: number, count: number): HistogramGraphDatum => ({
    id,
    bin0: id * 60,
    bin1: (id + 1) * 60,
    count,
    label: `${count}%`,
})

describe('buildTimeToConvertCompareRows', () => {
    it('returns rows with null previous when not comparing', () => {
        const current = [datum(0, 40), datum(1, 30)]

        const rows = buildTimeToConvertCompareRows(current, null)

        expect(rows).toEqual([
            { ...current[0], previous: null },
            { ...current[1], previous: null },
        ])
    })

    it('aligns previous bins positionally against shared boundaries', () => {
        const current = [datum(0, 40), datum(1, 30)]
        const previous = [datum(0, 38), datum(1, 31)]

        const rows = buildTimeToConvertCompareRows(current, previous)

        expect(rows[0].previous).toEqual(previous[0])
        expect(rows[1].previous).toEqual(previous[1])
    })

    it('leaves previous null where the previous series is shorter', () => {
        const current = [datum(0, 40), datum(1, 30), datum(2, 20)]
        const previous = [datum(0, 38)]

        const rows = buildTimeToConvertCompareRows(current, previous)

        expect(rows[0].previous).toEqual(previous[0])
        expect(rows[1].previous).toBeNull()
        expect(rows[2].previous).toBeNull()
    })
})
