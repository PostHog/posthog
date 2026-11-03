import { useEffect } from 'react'
import { Gesture, type NativeGesture, type PanGesture } from 'react-native-gesture-handler'
import { type SharedValue, useSharedValue, withTiming } from 'react-native-reanimated'

import { motion } from './tokens'

const DISMISS_DISTANCE = 80
const DISMISS_VELOCITY = 800

export interface SheetDrag {
    /** Downward offset in points while the user drags. Add it to the sheet's translateY. */
    drag: SharedValue<number>
    /** Attach with `GestureDetector` to the part of the sheet the user can drag down. */
    pan: PanGesture
}

/**
 * `scrollGesture` is a `Gesture.Native()` wrapping a scroll view inside the sheet. A drag that starts on that view
 * scrolls it, and the sheet follows only drags that start elsewhere, such as on the grabber or a header.
 */
export function useSheetDrag(visible: boolean, onClose: () => void, scrollGesture?: NativeGesture): SheetDrag {
    const drag = useSharedValue(0)

    useEffect(() => {
        if (visible) {
            drag.value = 0
        }
    }, [visible, drag])

    const pan = Gesture.Pan()
        .runOnJS(true)
        .activeOffsetY(8)
        .onUpdate((event) => {
            drag.value = Math.max(0, event.translationY)
        })
        .onEnd((event) => {
            if (event.translationY > DISMISS_DISTANCE || event.velocityY > DISMISS_VELOCITY) {
                onClose()
            } else {
                drag.value = withTiming(0, { duration: motion.sheet })
            }
        })
    if (scrollGesture) {
        pan.requireExternalGestureToFail(scrollGesture)
    }

    return { drag, pan }
}
