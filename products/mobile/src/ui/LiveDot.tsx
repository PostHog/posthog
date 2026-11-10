import { type ReactElement, useEffect } from 'react'
import { View } from 'react-native'
import Animated, {
    cancelAnimation,
    Easing,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withRepeat,
    withTiming,
} from 'react-native-reanimated'

import { createStyles, useColors } from './theme'

const SIZE = 10

/** Green and pulsing while updates arrive, gray while paused or reconnecting. Still when reduced motion is on. */
export function LiveDot({ on, animate }: { on: boolean; animate: boolean }): ReactElement {
    const colors = useColors()
    const styles = useStyles()
    const reduced = useReducedMotion()
    const pulse = useSharedValue(0)
    const pulsing = on && animate && !reduced
    useEffect(() => {
        if (pulsing) {
            pulse.value = withRepeat(withTiming(1, { duration: 1600, easing: Easing.out(Easing.quad) }), -1, false)
        } else {
            cancelAnimation(pulse)
            pulse.value = 0
        }
        return () => cancelAnimation(pulse)
    }, [pulsing, pulse])
    const halo = useAnimatedStyle(() => ({
        opacity: 0.5 * (1 - pulse.value),
        transform: [{ scale: 1 + pulse.value * 1.4 }],
    }))
    const color = on ? colors.diffGreen : colors.disabled
    return (
        <View style={styles.wrap} importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
            {pulsing ? <Animated.View style={[styles.dot, { backgroundColor: color }, halo]} /> : null}
            <View style={[styles.dot, { backgroundColor: color }]} testID={on ? 'live-dot-on' : 'live-dot-off'} />
        </View>
    )
}

const useStyles = createStyles(() => ({
    wrap: {
        width: SIZE,
        height: SIZE,
    },
    dot: {
        position: 'absolute',
        width: SIZE,
        height: SIZE,
        borderRadius: SIZE / 2,
    },
}))
