export const ADVENT_CARD_WIDTH = 320
export const ADVENT_CARD_INSET = 13
export const ADVENT_CARD_EDGE_GAP = 8

export interface AdventCardPlacement {
    isLeftward: boolean
    left: number
    width: number
}

export function adventCardPlacement(
    face: { left: number; size: number },
    stageWidth: number,
    row: number
): AdventCardPlacement {
    const roomRight = stageWidth - ADVENT_CARD_EDGE_GAP - (face.left - ADVENT_CARD_INSET)
    const roomLeft = face.left + face.size + ADVENT_CARD_INSET - ADVENT_CARD_EDGE_GAP
    const fitsRight = roomRight >= ADVENT_CARD_WIDTH
    const fitsLeft = roomLeft >= ADVENT_CARD_WIDTH
    const isLeftward = fitsLeft !== fitsRight ? fitsLeft : fitsLeft ? row !== 1 : roomLeft > roomRight
    const width = Math.min(ADVENT_CARD_WIDTH, isLeftward ? roomLeft : roomRight, stageWidth - 2 * ADVENT_CARD_EDGE_GAP)
    const anchored = isLeftward ? face.left + face.size + ADVENT_CARD_INSET - width : face.left - ADVENT_CARD_INSET
    const left = Math.min(Math.max(anchored, ADVENT_CARD_EDGE_GAP), stageWidth - ADVENT_CARD_EDGE_GAP - width)
    return { isLeftward, left, width }
}
