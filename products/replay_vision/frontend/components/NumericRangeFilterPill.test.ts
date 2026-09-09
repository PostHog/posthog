import { numericRangeLabel, toNumericBound } from './NumericRangeFilterPill'

describe('NumericRangeFilterPill', () => {
    describe('toNumericBound', () => {
        it('passes finite numbers through, including 0', () => {
            expect(toNumericBound(7)).toBe(7)
            expect(toNumericBound(0)).toBe(0)
            expect(toNumericBound(-1.5)).toBe(-1.5)
        })

        it('maps a cleared input (NaN) to null', () => {
            // LemonInput type="number" reports an empty field as NaN via valueAsNumber
            expect(toNumericBound(NaN)).toBeNull()
        })

        it('maps undefined and non-finite values to null', () => {
            expect(toNumericBound(undefined)).toBeNull()
            expect(toNumericBound(Infinity)).toBeNull()
            expect(toNumericBound(-Infinity)).toBeNull()
        })
    })

    describe('numericRangeLabel', () => {
        it('covers all four bound states', () => {
            expect(numericRangeLabel('Score', null, null)).toBe('Score')
            expect(numericRangeLabel('Score', 3, null)).toBe('Score ≥ 3')
            expect(numericRangeLabel('Score', null, 8)).toBe('Score ≤ 8')
            expect(numericRangeLabel('Score', 3, 8)).toBe('Score 3 to 8')
        })
    })
})
