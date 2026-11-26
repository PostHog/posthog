import { ADVENT_CARD_EDGE_GAP, ADVENT_CARD_INSET, ADVENT_CARD_WIDTH, adventCardPlacement } from './adventCardPlacement'

const FACE_SIZE = 64

function cardSpan(left: number, stageWidth: number, row: number): { from: number; to: number; isLeftward: boolean } {
    const { isLeftward, width } = adventCardPlacement({ left, size: FACE_SIZE }, stageWidth, row)
    const from = isLeftward ? left + FACE_SIZE + ADVENT_CARD_INSET - width : left - ADVENT_CARD_INSET
    return { from, to: from + width, isLeftward }
}

describe('adventCardPlacement', () => {
    it.each([
        ['the middle row on a wide stage', 500, 1200, 1, false],
        ['another row on a wide stage', 500, 1200, 0, true],
        ['a door near the left edge', 40, 1200, 0, false],
        ['a door near the right edge', 1100, 1200, 1, true],
    ])('opens %s to the side the rule picks', (_, left, stageWidth, row, isLeftward) => {
        const span = cardSpan(left, stageWidth, row)

        expect(span.isLeftward).toBe(isLeftward)
        expect(span.to - span.from).toBe(ADVENT_CARD_WIDTH)
    })

    it.each([0, 1, 2])('keeps the card inside a narrow stage when neither side has room, row %s', (row) => {
        const stageWidth = 520
        const margin = ADVENT_CARD_INSET + ADVENT_CARD_EDGE_GAP
        for (let left = margin; left <= stageWidth - FACE_SIZE - margin; left += 10) {
            const span = cardSpan(left, stageWidth, row)

            expect(span.from).toBeGreaterThanOrEqual(ADVENT_CARD_EDGE_GAP)
            expect(span.to).toBeLessThanOrEqual(stageWidth - ADVENT_CARD_EDGE_GAP)
        }
    })
})
