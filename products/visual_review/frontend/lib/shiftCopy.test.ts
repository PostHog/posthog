import type { RowShiftApi, ShiftBandApi } from '../generated/api.schemas'
import { describeShift } from './shiftCopy'

function rowShift(inserted: number, deleted: number, bands: ShiftBandApi[]): RowShiftApi {
    return {
        inserted_rows: inserted,
        deleted_rows: deleted,
        bands,
        residual_percentage: 0.5,
        raw_diff_percentage: 12,
    }
}

describe('describeShift', () => {
    test.each([
        ['one band holds every moved row', rowShift(40, 0, [{ kind: 'inserted', y: 300, rows: 40 }]), true],
        [
            'one band holds fewer rows than the counts',
            rowShift(65, 145, [{ kind: 'deleted', y: 300, rows: 80 }]),
            false,
        ],
        [
            'several bands',
            rowShift(40, 0, [
                { kind: 'inserted', y: 300, rows: 20 },
                { kind: 'inserted', y: 600, rows: 20 },
            ]),
            false,
        ],
    ])('names a position only when %s', (_, shift, namesPosition) => {
        for (const absorbed of [true, false]) {
            expect(describeShift(shift, absorbed)?.tooltip.includes('at y=300')).toBe(namesPosition)
        }
    })
})
