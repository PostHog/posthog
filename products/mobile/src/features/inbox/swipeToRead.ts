/** 1 when the row's action is a swipe right (mark read), -1 when it is a swipe left (mark unread). */
export type SwipeDirection = 1 | -1

/**
 * A narrow window still needs a deliberate drag to commit. It is not less than the row action's width plus two insets
 * in `SwipeToReadRow`, so the armed action never moves under the row.
 */
const MIN_COMMIT_DISTANCE = 104
const COMMIT_FRACTION = 0.4
/** The direction with no action moves the row this far at most, so the row feels alive but shows nothing. */
const INERT_LIMIT = 12
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

export function rowOffset(translationX: number, direction: SwipeDirection, width: number): number {
    'worklet'
    const travel = translationX * direction
    if (travel < 0) {
        return -direction * rubberBand(-travel, INERT_LIMIT)
    }
    if (travel <= width) {
        return translationX
    }
    return direction * (width + rubberBand(travel - width, OVERDRAG_LIMIT))
}
