import { type ReactElement, useEffect } from 'react'
import { StyleSheet, View } from 'react-native'
import Animated, {
    cancelAnimation,
    Easing,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withRepeat,
    withSequence,
    withTiming,
} from 'react-native-reanimated'
import Svg from 'react-native-svg'

import { type LogomarkPart, LogomarkShapes } from './LogomarkShapes'

const AIRTIME_MS = 720
const CADENCE_MS = 1400
const STAGGER_MS = 45
const PARTS: readonly LogomarkPart[] = ['blue', 'red', 'yellow', 'head']

function jumpOffset(elapsed: number, partIndex: number, height: number): number {
    'worklet'
    const progress = (elapsed - (PARTS.length - 1 - partIndex) * STAGGER_MS) / AIRTIME_MS
    if (progress <= 0 || progress >= 1) {
        return 0
    }
    // Zero velocity at takeoff, the peak and landing keeps the loop from snapping.
    const lift = Math.sin(Math.PI * progress)
    return ((-8 * height) / 28) * lift * lift
}

export function AnimatedLogomark({
    height = 65,
    animate = true,
}: {
    height?: number
    animate?: boolean
}): ReactElement {
    const reduceMotion = useReducedMotion()
    const elapsed = useSharedValue(0)

    useEffect(() => {
        if (reduceMotion) {
            elapsed.value = 0
            return
        }
        if (!animate && elapsed.value === 0) {
            return
        }
        const finishHop = withTiming(CADENCE_MS, {
            duration: Math.max(0, CADENCE_MS - elapsed.value),
            easing: Easing.linear,
        })
        elapsed.value = animate
            ? withSequence(
                  finishHop,
                  withTiming(0, { duration: 0 }),
                  withRepeat(withTiming(CADENCE_MS, { duration: CADENCE_MS, easing: Easing.linear }), -1)
              )
            : finishHop
        return () => {
            cancelAnimation(elapsed)
        }
    }, [animate, reduceMotion, elapsed])

    const partStyles = [
        useAnimatedStyle(() => ({ transform: [{ translateY: jumpOffset(elapsed.value, 0, height) }] })),
        useAnimatedStyle(() => ({ transform: [{ translateY: jumpOffset(elapsed.value, 1, height) }] })),
        useAnimatedStyle(() => ({ transform: [{ translateY: jumpOffset(elapsed.value, 2, height) }] })),
        useAnimatedStyle(() => ({ transform: [{ translateY: jumpOffset(elapsed.value, 3, height) }] })),
    ]
    const width = (height * 52) / 28

    return (
        <View style={{ width, height }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            {PARTS.map((part, index) => (
                <Animated.View key={part} style={[StyleSheet.absoluteFill, partStyles[index]]}>
                    <Svg width={width} height={height} viewBox="0 0 52 28">
                        <LogomarkShapes part={part} />
                    </Svg>
                </Animated.View>
            ))}
        </View>
    )
}
