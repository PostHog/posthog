import { type ComponentType, type ReactElement, type ReactNode, useCallback, useMemo, useRef, useState } from 'react'
import { type LayoutChangeEvent, Platform, Text, View, type ViewStyle } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, {
    Easing,
    Extrapolation,
    interpolate,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withSpring,
    withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { haptic } from '@/lib/haptics'
import { MailOpenIcon } from '@/ui/icons/MailOpenIcon'
import { MailUnreadIcon } from '@/ui/icons/MailUnreadIcon'
import type { IconProps } from '@/ui/icons/types'
import { createStyles, useTheme } from '@/ui/theme'
import { iconSizes, layout, motion, type } from '@/ui/tokens'

import { commitDistance, rowOffset, type SwipeDirection } from './swipeToRead'

/** Horizontal travel before the row moves. Below it, the touch stays a tap or a long press. */
const ACTIVE_OFFSET_X = 14
const FAIL_OFFSET_Y = 10
const UNDERLAY_FADE_DISTANCE = 24
const ACTION_INSET = 20
// Fits "Unread" in `type.buttonSmall` with room to spare, because a clipped label ends in an ellipsis.
const ACTION_WIDTH = 64
const IDLE_SCALE = 0.7
const IDLE_OPACITY = 0.6
// Both springs settle with a small overshoot at most, so the pop reads as a snap and not a bounce.
const ARM_SPRING = { damping: 24, stiffness: 320 }
const RETURN_SPRING = { damping: 32, stiffness: 320 }
const COMMIT_SLIDE_MS = 180
// react-native-web does not cancel a press when the pan activates, so the mouseup that ends a drag also presses the
// row. That mouseup can arrive before or after the pan ends, so the block lasts a little past the end.
const BLOCK_PRESS_AFTER_SWIPE = Platform.OS === 'web'
const PRESS_GRACE_MS = 100

/**
 * The action's look for one frame. Idle, it sits ACTION_INSET from the screen edge. Armed, it rides with its far edge
 * ACTION_INSET inside the row's edge. `commitDistance` is at least ACTION_WIDTH + 2 * ACTION_INSET (104pt), so the
 * armed action never moves under the row. Update both together.
 */
function actionLook(
    direction: SwipeDirection,
    shownDirection: SwipeDirection,
    offset: number,
    armed: number
): ViewStyle {
    'worklet'
    const settled = Math.min(1, armed)
    const revealed = Math.max(0, offset * shownDirection)
    const follow = Math.max(0, revealed - ACTION_WIDTH - ACTION_INSET * 2) * settled
    return {
        opacity: shownDirection === direction ? IDLE_OPACITY + (1 - IDLE_OPACITY) * settled : 0,
        transform: [{ translateX: direction * follow }, { scale: IDLE_SCALE + (1 - IDLE_SCALE) * armed }],
    }
}

interface SwipeToReadRowProps {
    onMarkRead: () => void
    onMarkUnread: () => void
    /** `pressBlocked` is true while a drag runs and briefly after it, so the row can ignore the press a drag makes. */
    children: (pressBlocked: () => boolean) => ReactNode
}

/**
 * A full-swipe commit around an inbox row: swipe right marks the report read, swipe left marks it unread. Both
 * directions always play, so a swipe toward the state the row already has still gives the same feedback. The
 * children keep their own press and long press, because the pan activates only after 14pt of horizontal travel.
 */
export function SwipeToReadRow({ onMarkRead, onMarkUnread, children }: SwipeToReadRowProps): ReactElement {
    const styles = useStyles()
    // Plain strings, so the underlay worklet can capture them.
    const { read: readColor, unread: unreadColor } = useTheme().swipeColors
    const reduceMotion = useReducedMotion()
    const [width, setWidth] = useState(0)
    const offset = useSharedValue(0)
    /** 0 to 1 with spring overshoot: how far the action has moved into its armed look. */
    const armed = useSharedValue(0)
    const isArmed = useSharedValue(false)
    /** The side of the drag on screen. Only a gesture frame sets it, so the return animation never flips it. */
    const shownDirection = useSharedValue<SwipeDirection>(1)
    const settling = useSharedValue(false)
    const live = useSharedValue(false)
    const startX = useSharedValue(0)
    const swiping = useRef(false)
    const unblockTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
    const markSwipeStart = useCallback((): void => {
        clearTimeout(unblockTimer.current)
        swiping.current = true
    }, [])
    const markSwipeEnd = useCallback((): void => {
        if (!swiping.current) {
            return
        }
        clearTimeout(unblockTimer.current)
        unblockTimer.current = setTimeout(() => {
            swiping.current = false
        }, PRESS_GRACE_MS)
    }, [])
    const pressBlocked = useCallback((): boolean => swiping.current, [])

    const pan = useMemo(() => {
        const threshold = commitDistance(width)
        const [x1, y1, x2, y2] = motion.emphasizedBezier
        const setArmed = (next: boolean): void => {
            'worklet'
            isArmed.value = next
            armed.value = reduceMotion ? Number(next) : withSpring(Number(next), ARM_SPRING)
        }
        const springBack = (): void => {
            'worklet'
            setArmed(false)
            offset.value = reduceMotion ? 0 : withSpring(0, RETURN_SPRING)
        }
        const commit = (markRead: boolean): void => {
            if (markRead) {
                onMarkRead()
            } else {
                onMarkUnread()
            }
        }
        return Gesture.Pan()
            .enabled(width > 0)
            .activeOffsetX([-ACTIVE_OFFSET_X, ACTIVE_OFFSET_X])
            .failOffsetY([-FAIL_OFFSET_Y, FAIL_OFFSET_Y])
            .onStart((event) => {
                'worklet'
                if (BLOCK_PRESS_AFTER_SWIPE) {
                    scheduleOnRN(markSwipeStart)
                }
                // A drag that starts while the last commit settles would fight the return animation.
                live.value = !settling.value
                if (!live.value) {
                    return
                }
                startX.value = event.translationX
            })
            .onUpdate((event) => {
                'worklet'
                if (!live.value) {
                    return
                }
                offset.value = rowOffset(event.translationX - startX.value, width)
                if (offset.value !== 0) {
                    shownDirection.value = offset.value > 0 ? 1 : -1
                }
                const next = Math.abs(offset.value) >= threshold
                if (next !== isArmed.value) {
                    setArmed(next)
                    // Arming is the moment the swipe takes effect, so it gets the impact. Leaving the zone only ticks.
                    scheduleOnRN(haptic, next ? 'light' : 'selection')
                }
            })
            .onEnd((_event, success) => {
                'worklet'
                if (!live.value) {
                    return
                }
                live.value = false
                if (!success || !isArmed.value) {
                    springBack()
                    return
                }
                const direction = shownDirection.value
                scheduleOnRN(haptic, 'light')
                if (reduceMotion) {
                    setArmed(false)
                    offset.value = 0
                    scheduleOnRN(commit, direction === 1)
                    return
                }
                settling.value = true
                offset.value = withTiming(
                    direction * width,
                    { duration: COMMIT_SLIDE_MS, easing: Easing.bezier(x1, y1, x2, y2) },
                    () => {
                        scheduleOnRN(commit, direction === 1)
                        offset.value = withSpring(0, { ...RETURN_SPRING, overshootClamping: true }, () => {
                            isArmed.value = false
                            armed.value = 0
                            settling.value = false
                        })
                    }
                )
            })
            .onFinalize(() => {
                'worklet'
                if (BLOCK_PRESS_AFTER_SWIPE) {
                    scheduleOnRN(markSwipeEnd)
                }
            })
    }, [
        width,
        reduceMotion,
        onMarkRead,
        onMarkUnread,
        offset,
        armed,
        isArmed,
        shownDirection,
        settling,
        live,
        startX,
        markSwipeStart,
        markSwipeEnd,
    ])

    const foregroundStyle = useAnimatedStyle(() => ({ transform: [{ translateX: offset.value }] }))
    const underlayStyle = useAnimatedStyle(() => ({
        backgroundColor: shownDirection.value === 1 ? readColor : unreadColor,
        opacity: interpolate(
            offset.value * shownDirection.value,
            [0, UNDERLAY_FADE_DISTANCE],
            [0, 1],
            Extrapolation.CLAMP
        ),
    }))
    // Each callback reads the shared values itself, because Reanimated only registers the values read in the callback.
    const readActionStyle = useAnimatedStyle(() => actionLook(1, shownDirection.value, offset.value, armed.value))
    const unreadActionStyle = useAnimatedStyle(() => actionLook(-1, shownDirection.value, offset.value, armed.value))

    const onLayout = (event: LayoutChangeEvent): void => setWidth(event.nativeEvent.layout.width)

    return (
        <GestureDetector gesture={pan}>
            <View style={styles.container} onLayout={onLayout}>
                <Animated.View
                    style={[styles.underlay, underlayStyle]}
                    accessibilityElementsHidden
                    importantForAccessibility="no-hide-descendants"
                >
                    <Animated.View style={[styles.action, styles.leading, readActionStyle]}>
                        <SwipeAction label="Read" Icon={MailOpenIcon} />
                    </Animated.View>
                    <Animated.View style={[styles.action, styles.trailing, unreadActionStyle]}>
                        <SwipeAction label="Unread" Icon={MailUnreadIcon} />
                    </Animated.View>
                </Animated.View>
                <Animated.View style={[styles.foreground, foregroundStyle]}>{children(pressBlocked)}</Animated.View>
            </View>
        </GestureDetector>
    )
}

function SwipeAction({ label, Icon }: { label: string; Icon: ComponentType<IconProps> }): ReactElement {
    const styles = useStyles()
    const { swipeColors } = useTheme()
    return (
        <>
            <Icon size={iconSizes.navigation} color={swipeColors.onAction} />
            <Text style={styles.label} numberOfLines={1}>
                {label}
            </Text>
        </>
    )
}

const useStyles = createStyles(({ colors, swipeColors }) => ({
    // The list content is inset by the gutter, so the row reaches into it and the underlay runs edge to edge.
    container: {
        marginHorizontal: -layout.inboxGutter,
        overflow: 'hidden',
        backgroundColor: colors.background,
    },
    underlay: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        pointerEvents: 'none',
    },
    foreground: {
        paddingHorizontal: layout.inboxGutter,
        backgroundColor: colors.background,
    },
    action: {
        position: 'absolute',
        top: 0,
        bottom: 0,
        width: ACTION_WIDTH,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2,
    },
    leading: { left: ACTION_INSET },
    trailing: { right: ACTION_INSET },
    label: {
        ...type.buttonSmall,
        color: swipeColors.onAction,
    },
}))
