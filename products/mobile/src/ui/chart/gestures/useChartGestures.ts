import { useMemo } from 'react'
import { type ComposedGesture, Gesture } from 'react-native-gesture-handler'
import { scheduleOnRN } from 'react-native-worklets'

import { nearestIndex } from '../chartMath'

// A drag scrubs once it moves 8pt sideways, and a 10pt vertical move first hands the touch to the surrounding
// ScrollView. Victory's default instead waits for a 100ms long press, which makes scrubbing feel slow.
export const PRESS_CONFIG = {
    pan: { activeOffsetX: [-8, 8] as [number, number], failOffsetY: [-10, 10] as [number, number] },
}
// On web, the browser keeps vertical touch scrolling while the chart takes horizontal drags.
export const GESTURE_CONFIG = { touchAction: 'pan-y' } as const
const TAP_MAX_DISTANCE = 10

/** The tap that selects the bucket nearest the finger. Victory adds its own press pan next to it. */
export function useChartGestures(xs: number[], onTap: (index: number) => void): ComposedGesture {
    return useMemo(() => {
        const tap = Gesture.Tap()
            .maxDistance(TAP_MAX_DISTANCE)
            .onEnd((event, success) => {
                if (!success) {
                    return
                }
                const index = nearestIndex(xs, event.x)
                if (index >= 0) {
                    scheduleOnRN(onTap, index)
                }
            })
        return Gesture.Race(tap)
    }, [xs, onTap])
}
