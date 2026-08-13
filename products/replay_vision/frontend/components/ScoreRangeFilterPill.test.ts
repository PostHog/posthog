import { scoreRangeLabel, toScoreBound } from './ScoreRangeFilterPill'

describe('toScoreBound', () => {
    it('passes finite numbers through, including 0', () => {
        expect(toScoreBound(7)).toBe(7)
        expect(toScoreBound(0)).toBe(0)
        expect(toScoreBound(-1.5)).toBe(-1.5)
    })

    it('maps a cleared input (NaN) to null', () => {
        // LemonInput type="number" reports an empty field as NaN via valueAsNumber
        expect(toScoreBound(NaN)).toBeNull()
    })

    it('maps undefined and non-finite values to null', () => {
        expect(toScoreBound(undefined)).toBeNull()
        expect(toScoreBound(Infinity)).toBeNull()
        expect(toScoreBound(-Infinity)).toBeNull()
    })
})

describe('scoreRangeLabel', () => {
    it('covers all four bound states', () => {
        expect(scoreRangeLabel(null, null)).toBe('Score')
        expect(scoreRangeLabel(3, null)).toBe('Score ≥ 3')
        expect(scoreRangeLabel(null, 8)).toBe('Score ≤ 8')
        expect(scoreRangeLabel(3, 8)).toBe('Score 3 to 8')
    })
})
