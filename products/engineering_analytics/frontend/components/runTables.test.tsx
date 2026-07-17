import { formatCost } from './runTables'

describe('formatCost', () => {
    it.each([
        [null, '—'],
        [0, '$0.00'],
        // Sub-cent positives must not read as free — a short self-hosted job at the reference rate.
        [0.004, '<$0.01'],
        [0.009, '<$0.01'],
        [0.01, '$0.01'],
        [0.38, '$0.38'],
        [12.5, '$12.50'],
    ])('formats %p as %p', (usd, expected) => {
        expect(formatCost(usd)).toBe(expected)
    })
})
