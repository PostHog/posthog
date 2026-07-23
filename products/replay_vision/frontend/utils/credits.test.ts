import { creditsToUsd, formatCreditCount, formatCredits, formatCreditsRange } from './credits'

describe('credits formatting', () => {
    it.each([
        [0, '0 credits (≈ $0.00)'],
        [1, '1 credit (≈ $0.01)'],
        [2, '2 credits (≈ $0.02)'],
        [500, '500 credits (≈ $5.00)'],
        [5000, '5,000 credits (≈ $50.00)'],
        // Fractional estimates round to whole credits, and the dollar anchor follows the rounded count.
        [512.4, '512 credits (≈ $5.12)'],
        [512.6, '513 credits (≈ $5.13)'],
    ])('formatCredits(%p) -> %p', (credits, expected) => {
        expect(formatCredits(credits)).toBe(expected)
    })

    it.each([
        [0, '0 credits'],
        [1, '1 credit'],
        [1500, '1,500 credits'],
    ])('formatCreditCount(%p) -> %p', (credits, expected) => {
        expect(formatCreditCount(credits)).toBe(expected)
    })

    it.each([
        [5, '$0.05'],
        [1200, '$12.00'],
    ])('creditsToUsd(%p) -> %p', (credits, expected) => {
        expect(creditsToUsd(credits)).toBe(expected)
    })

    it.each([
        [1200, 5000, '1,200 of 5,000 credits (≈ $12.00 of $50.00)'],
        [1, 1, '1 of 1 credit (≈ $0.01 of $0.01)'],
    ])('formatCreditsRange(%p, %p) -> %p', (used, total, expected) => {
        expect(formatCreditsRange(used, total)).toBe(expected)
    })
})
