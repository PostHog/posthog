/** 1 when the row's action is a swipe right (mark read), -1 when it is a swipe left (mark unread). */
export type SwipeDirection = 1 | -1

/**
 * A narrow window still needs a deliberate drag to commit. It is not less than the row action's width plus two insets
 * in `SwipeToReadRow`, so the armed action never moves under the row.
 */
const MIN_COMMIT_DISTANCE = 104
const COMMIT_FRACTION = 0.3
const OVERDRAG_LIMIT = 48
/** The coefficient iOS scroll views use for their rubber band. */
const RUBBER_BAND_COEFFICIENT = 0.55

export function commitDistance(width: number): number {
    'worklet'
    return Math.max(MIN_COMMIT_DISTANCE, width * COMMIT_FRACTION)
}

export function rubberBand(distance: number, limit: number): number {
    'worklet'
    return limit * (1 - 1 / ((distance * RUBBER_BAND_COEFFICIENT) / limit + 1))
}

export function rowOffset(translationX: number, width: number): number {
    'worklet'
    const travel = Math.abs(translationX)
    if (travel <= width) {
        return translationX
    }
    const direction: SwipeDirection = translationX > 0 ? 1 : -1
    return direction * (width + rubberBand(travel - width, OVERDRAG_LIMIT))
}
