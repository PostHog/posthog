import { toSimilarityScore } from './similarFingerprintsLogic'

describe('similarFingerprintsLogic', () => {
    // Cosine distance runs 0..2, so anything past 1 has to clamp instead of going negative.
    it.each([
        [0, 100],
        [0.02, 100],
        [0.06, 95],
        [0.5, 50],
        [1, 0],
        [1.4, 0],
        [2, 0],
    ])('scores a cosine distance of %p as %p%%', (distance, expected) => {
        expect(toSimilarityScore(distance)).toBe(expected)
    })
})
