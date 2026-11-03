import { useMemo } from 'react'
import { type ComposedGesture, Gesture, type PanGesture, type TouchData } from 'react-native-gesture-handler'
import { type SharedValue, useSharedValue } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { nearestIndex, snapToValue } from '../chartMath'
import type { ChartSelectionEvents, ChartSelectionValues } from '../selection/useChartSelection'
import type { ChartVariant } from '../types'

/** Below HOLD_MS, so a hold never also counts as a tap. */
export const TAP_MAX_MS = 250
export const TAP_MAX_TRAVEL = 10
/** A still finger for this long starts a scrub. After that, vertical travel scrubs too. */
export const HOLD_MS = 300
/** Horizontal travel before a drag in a list scrubs: within about 34 degrees of horizontal, so flicks scroll. */
export const INLINE_ACTIVATE_X = 12
/** Vertical travel that hands the touch to the list first. Android's ScrollView slop is about 8dp too. */
export const INLINE_FAIL_Y = 8
export const FULLSCREEN_MIN_TRAVEL = 4
/** A tap that lands this soon after the list last moved stopped a fling, so it selects nothing. */
export const LIST_SETTLE_MS = 150

const NO_TOUCH = -1

export interface ChartGestureInput {
    variant: ChartVariant
    /** The x of each bucket, in the chart's coordinates. */
    xs: number[]
    /** 0 where a bucket can be selected, NaN where it has no visible value. */
    mask: number[]
    values: ChartSelectionValues
    events: ChartSelectionEvents
    listMovedAt: SharedValue<number> | null
}

interface TouchTracking {
    idA: SharedValue<number>
    idB: SharedValue<number>
    xA: SharedValue<number>
    xB: SharedValue<number>
    tapBlocked: SharedValue<boolean>
    /** 1 for the drag, 2 for the hold: the pan that won the race. 0 before either starts. */
    activePan: SharedValue<number>
}

/**
 * One composition for every chart: `Race(drag, hold, tap)`. Pointer 1 drives marker A and pointer 2 drives marker B.
 * Every callback runs on the UI thread; the JS side only hears about bucket changes.
 */
export function useChartGestures(input: ChartGestureInput): ComposedGesture {
    const idA = useSharedValue(NO_TOUCH)
    const idB = useSharedValue(NO_TOUCH)
    const xA = useSharedValue(0)
    const xB = useSharedValue(0)
    const tapBlocked = useSharedValue(false)
    const activePan = useSharedValue(0)

    const { variant, xs, mask, values, events, listMovedAt } = input
    return useMemo(() => {
        const tracking: TouchTracking = { idA, idB, xA, xB, tapBlocked, activePan }
        const { selA, selB } = values

        const bucketAt = (x: number): number => {
            'worklet'
            return snapToValue(mask, nearestIndex(xs, x))
        }

        const tap = Gesture.Tap()
            .maxDuration(TAP_MAX_MS)
            .maxDistance(TAP_MAX_TRAVEL)
            .onTouchesDown((event) => {
                'worklet'
                trackTouchesDown(event.changedTouches, event.numberOfTouches, tracking, listMovedAt)
            })
            .onEnd((event, success) => {
                'worklet'
                if (!success || tapBlocked.value) {
                    return
                }
                const index = bucketAt(event.x)
                if (index < 0) {
                    return
                }
                if (selB.value >= 0) {
                    selB.value = -1
                    selA.value = index
                    scheduleOnRN(events.pinned, index, 'tap')
                } else if (selA.value === index) {
                    selA.value = -1
                    scheduleOnRN(events.dismissed, 'tap_again')
                } else {
                    selA.value = index
                    scheduleOnRN(events.pinned, index, 'tap')
                }
            })

        const drag = Gesture.Pan().maxPointers(2).shouldCancelWhenOutside(false)
        if (variant === 'fullscreen') {
            drag.minDistance(FULLSCREEN_MIN_TRAVEL)
        } else {
            drag.activeOffsetX([-INLINE_ACTIVATE_X, INLINE_ACTIVATE_X]).failOffsetY([-INLINE_FAIL_Y, INLINE_FAIL_Y])
        }
        const hold = Gesture.Pan().maxPointers(2).shouldCancelWhenOutside(false).activateAfterLongPress(HOLD_MS)

        const attachScrub = (pan: PanGesture, panId: number): void => {
            pan.onTouchesDown((event) => {
                'worklet'
                trackTouchesDown(event.changedTouches, event.numberOfTouches, tracking, listMovedAt)
                // A second finger that lands during a scrub starts the compare at once.
                if (activePan.value === panId && idB.value !== NO_TOUCH && selB.value < 0) {
                    selB.value = bucketAt(xB.value)
                    scheduleOnRN(events.rangeStarted)
                }
            })
                .onStart(() => {
                    'worklet'
                    activePan.value = panId
                    values.scrubbing.value = true
                    const index = bucketAt(xA.value)
                    selA.value = index
                    selB.value = idB.value === NO_TOUCH ? -1 : bucketAt(xB.value)
                    scheduleOnRN(events.scrubStarted, index, panId === 2)
                    if (selB.value >= 0) {
                        scheduleOnRN(events.rangeStarted)
                    }
                })
                .onTouchesMove((event) => {
                    'worklet'
                    for (const touch of event.allTouches) {
                        if (touch.id === idA.value) {
                            xA.value = touch.x
                        } else if (touch.id === idB.value) {
                            xB.value = touch.x
                        }
                    }
                    if (activePan.value !== panId) {
                        return
                    }
                    const a = bucketAt(xA.value)
                    if (idA.value !== NO_TOUCH && a >= 0 && a !== selA.value) {
                        selA.value = a
                        scheduleOnRN(events.scrubMoved, a)
                    }
                    const b = bucketAt(xB.value)
                    if (idB.value !== NO_TOUCH && b >= 0 && b !== selB.value) {
                        selB.value = b
                        scheduleOnRN(events.rangeMoved)
                    }
                })
                .onTouchesUp((event) => {
                    'worklet'
                    // The lifted finger's marker stays where it was; the other finger keeps moving its own.
                    for (const touch of event.changedTouches) {
                        if (touch.id === idA.value) {
                            idA.value = NO_TOUCH
                        } else if (touch.id === idB.value) {
                            idB.value = NO_TOUCH
                        }
                    }
                })
                .onFinalize(() => {
                    'worklet'
                    if (activePan.value !== panId) {
                        return
                    }
                    activePan.value = 0
                    values.scrubbing.value = false
                    scheduleOnRN(events.scrubEnded)
                })
        }
        attachScrub(drag, 1)
        attachScrub(hold, 2)
        return Gesture.Race(drag, hold, tap)
    }, [variant, xs, mask, values, events, listMovedAt, idA, idB, xA, xB, tapBlocked, activePan])
}

/** The web keeps vertical page scrolling for charts in a list. Full screen takes every direction. */
export function gestureHandlerConfig(variant: ChartVariant): { touchAction: 'pan-y' | 'none' } {
    return { touchAction: variant === 'fullscreen' ? 'none' : 'pan-y' }
}

// All three gestures get the same touch events, so this runs up to three times per touch and must be idempotent.
function trackTouchesDown(
    changed: TouchData[],
    numberOfTouches: number,
    tracking: TouchTracking,
    listMovedAt: SharedValue<number> | null
): void {
    'worklet'
    const { idA, idB, xA, xB, tapBlocked } = tracking
    if (numberOfTouches <= changed.length) {
        // A fresh touch sequence: forget fingers from the last one.
        idA.value = NO_TOUCH
        idB.value = NO_TOUCH
        tapBlocked.value = listMovedAt !== null && Date.now() - listMovedAt.value < LIST_SETTLE_MS
    }
    for (const touch of changed) {
        if (touch.id === idA.value || touch.id === idB.value) {
            continue
        }
        if (idA.value === NO_TOUCH) {
            idA.value = touch.id
            xA.value = touch.x
        } else if (idB.value === NO_TOUCH) {
            idB.value = touch.id
            xB.value = touch.x
        }
    }
}
