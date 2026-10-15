import { type ReactElement, useEffect } from 'react'
import { type StyleProp, StyleSheet, Text, type TextStyle } from 'react-native'
import Animated, {
    cancelAnimation,
    Easing,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withRepeat,
    withTiming,
} from 'react-native-reanimated'

import { CheckIcon } from './icons/CheckIcon'
import { RefreshIcon } from './icons/RefreshIcon'
import { Pressable44 } from './Pressable44'
import { colors, radii } from './tokens'

/** `busy`: a request of the screen runs. `blocked`: nothing may be forced, so a tap only explains why. */
export type RefreshButtonState = 'idle' | 'busy' | 'blocked'

interface RefreshButtonProps {
    state: RefreshButtonState
    onPress: () => void
    /** Spoken while blocked: the same words as the hint, such as "You can refresh again in 3 min." */
    blockedLabel?: string
    /** No taps at all, for example while the screen has nothing loaded. */
    disabled?: boolean
    testID?: string
}

const SPIN_MS = 900

/**
 * The top-right refresh button of the Views screens. It spins while the screen updates. When nothing may be forced it
 * shows a check drawn as disabled, but it still takes the tap, so the screen can show why nothing happens.
 */
export function RefreshButton({
    state,
    onPress,
    blockedLabel,
    disabled = false,
    testID = 'views-refresh',
}: RefreshButtonProps): ReactElement {
    const reduceMotion = useReducedMotion()
    const rotation = useSharedValue(0)
    const spinning = state === 'busy' && !reduceMotion

    useEffect(() => {
        if (spinning) {
            rotation.value = 0
            rotation.value = withRepeat(withTiming(360, { duration: SPIN_MS, easing: Easing.linear }), -1, false)
            return
        }
        cancelAnimation(rotation)
        rotation.value = 0
    }, [spinning, rotation])

    const spinStyle = useAnimatedStyle(() => ({ transform: [{ rotate: `${rotation.value}deg` }] }))

    const blocked = state === 'blocked' && !disabled
    const iconColor =
        disabled || blocked ? colors.disabled : state === 'busy' && reduceMotion ? colors.tertiary : colors.ink
    return (
        <Pressable44
            onPress={onPress}
            disabled={disabled || state === 'busy'}
            accessibilityLabel={blocked ? (blockedLabel ?? 'Up to date') : state === 'busy' ? 'Updating' : 'Refresh'}
            accessibilityState={{ busy: state === 'busy', disabled: disabled || blocked }}
            pressedBackground={blocked ? undefined : colors.background}
            style={styles.button}
            testID={testID}
        >
            {blocked ? (
                <CheckIcon size={22} color={iconColor} />
            ) : (
                <Animated.View style={spinStyle}>
                    <RefreshIcon size={22} color={iconColor} />
                </Animated.View>
            )}
        </Pressable44>
    )
}

interface RefreshHintProps {
    text: string
    style?: StyleProp<TextStyle>
    testID?: string
}

/**
 * The inline hint under the status line. Place it so that showing it does not move the layout, for example
 * absolutely positioned in the header's bottom padding.
 */
export function RefreshHint({ text, style, testID = 'views-refresh-hint' }: RefreshHintProps): ReactElement {
    return (
        <Text
            style={[styles.hint, style]}
            numberOfLines={1}
            accessibilityLiveRegion="polite"
            accessibilityRole="text"
            testID={testID}
        >
            {text}
        </Text>
    )
}

const styles = StyleSheet.create({
    button: {
        width: 56,
        height: 46,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
    },
    hint: {
        fontSize: 13,
        lineHeight: 16,
        fontWeight: '600',
        color: colors.muted,
    },
})
