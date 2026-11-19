import type { ReactElement } from 'react'
import { Pressable, StyleSheet } from 'react-native'
import Animated, { type SharedValue, useAnimatedStyle } from 'react-native-reanimated'

interface ScrimProps {
    color: string
    progress: SharedValue<number>
    /** Omit to make the scrim swallow taps without closing anything. */
    onPress?: () => void
    accessibilityLabel?: string
}

export function Scrim({ color, progress, onPress, accessibilityLabel = 'Close' }: ScrimProps): ReactElement {
    const animatedStyle = useAnimatedStyle(() => ({ opacity: progress.value }))
    return (
        <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: color }, animatedStyle]}>
            <Pressable
                style={StyleSheet.absoluteFill}
                onPress={onPress}
                disabled={!onPress}
                accessibilityRole="button"
                accessibilityLabel={accessibilityLabel}
                importantForAccessibility={onPress ? 'yes' : 'no-hide-descendants'}
            />
        </Animated.View>
    )
}
