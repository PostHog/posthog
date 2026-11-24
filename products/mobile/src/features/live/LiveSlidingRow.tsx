import { type ReactElement, type ReactNode, useEffect } from 'react'
import type { StyleProp, ViewProps, ViewStyle } from 'react-native'
import Animated, {
    Easing,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withTiming,
} from 'react-native-reanimated'

import { createStyles } from '@/ui/theme'

export const LIVE_ROW_HEIGHT = 44
const MOVE_MS = 450

interface LiveSlidingRowProps extends Pick<ViewProps, 'accessible' | 'accessibilityLabel' | 'testID'> {
    /** The row's rank. A new rank slides the row to its place; the parent is `count × LIVE_ROW_HEIGHT` tall. */
    index: number
    style?: StyleProp<ViewStyle>
    children: ReactNode
}

/** A row of the web's animated top lists: it slides to its new place when its rank changes. */
export function LiveSlidingRow({ index, style, children, ...rest }: LiveSlidingRowProps): ReactElement {
    const styles = useStyles()
    const reduced = useReducedMotion()
    const y = useSharedValue(index * LIVE_ROW_HEIGHT)
    useEffect(() => {
        const target = index * LIVE_ROW_HEIGHT
        y.value = reduced ? target : withTiming(target, { duration: MOVE_MS, easing: Easing.out(Easing.cubic) })
    }, [index, reduced, y])
    const position = useAnimatedStyle(() => ({ transform: [{ translateY: y.value }] }))
    return (
        <Animated.View {...rest} style={[styles.row, style, position]}>
            {children}
        </Animated.View>
    )
}

const useStyles = createStyles(() => ({
    row: {
        position: 'absolute',
        left: 0,
        right: 0,
        height: LIVE_ROW_HEIGHT,
    },
}))
