import { ADVENT_CARD_EDGE_GAP, ADVENT_CARD_INSET, ADVENT_CARD_WIDTH, adventCardPlacement } from './adventCardPlacement'

const FACE_SIZE = 64

describe('adventCardPlacement', () => {
    it.each([
        ['the middle row on a wide stage', 500, 1200, 1, false],
        ['another row on a wide stage', 500, 1200, 0, true],
        ['a door near the left edge', 40, 1200, 0, false],
        ['a door near the right edge', 1100, 1200, 1, true],
    ])('opens %s to the side the rule picks, anchored on the door', (_, left, stageWidth, row, isLeftward) => {
        const card = adventCardPlacement({ left, size: FACE_SIZE }, stageWidth, row)

        expect(card.isLeftward).toBe(isLeftward)
        expect(card.width).toBe(ADVENT_CARD_WIDTH)
        expect(card.left).toBe(
            isLeftward ? left + FACE_SIZE + ADVENT_CARD_INSET - ADVENT_CARD_WIDTH : left - ADVENT_CARD_INSET
        )
    })

    it.each([
        [0, 320],
        [1, 320],
        [2, 320],
        [0, 520],
        [1, 520],
        [2, 520],
    ])(
        'keeps the card inside the stage and its copy of the door on the visible door and inside the card, row %s on a %spx stage',
        (row, stageWidth) => {
            for (let left = 4 - FACE_SIZE; left <= stageWidth - 4; left += 4) {
                const shownLeft = Math.min(Math.max(left, 0), stageWidth - FACE_SIZE)
                const card = adventCardPlacement({ left, size: FACE_SIZE }, stageWidth, row)

                const faceCopyLeft = card.isLeftward
                    ? card.left + card.width - card.faceInset - FACE_SIZE
                    : card.left + card.faceInset

                const isDoorClearOfEdges =
                    left >= ADVENT_CARD_EDGE_GAP && left + FACE_SIZE <= stageWidth - ADVENT_CARD_EDGE_GAP
                const gap = isDoorClearOfEdges ? ADVENT_CARD_EDGE_GAP : 0

                expect(card.left).toBeGreaterThanOrEqual(gap)
                expect(card.left + card.width).toBeLessThanOrEqual(stageWidth - gap)
                expect(faceCopyLeft).toBe(shownLeft)
                expect(card.faceInset).toBeGreaterThanOrEqual(0)
                expect(card.faceInset + FACE_SIZE).toBeLessThanOrEqual(card.width)
            }
        }
    )
})
