import { type ReactElement, useCallback, useEffect, useState } from 'react'
import { type LayoutChangeEvent, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, {
    interpolate,
    type SharedValue,
    useAnimatedReaction,
    useAnimatedStyle,
    useDerivedValue,
    useSharedValue,
    withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { haptic } from '@/lib/haptics'
import { createStyles } from '@/ui/theme'
import { fonts } from '@/ui/tokens'

import { formatOffset } from '../sessionAdapters'
import { perfMark } from './feedPerf'
import { feedColors, feedTextShadow, tickColors } from './feedStyle'
import type { ScrubberTick } from './scrubberMarks'

interface FeedScrubberProps {
    /** The range in JS, for placing the marks. The bar itself follows `rangeStart` and `rangeEnd`. */
    start: number
    end: number
    /**
     * The range the bar draws. The card owns them, so a tab swipe animates the range on the UI thread before the
     * card renders in its new mode.
     */
    rangeStart: SharedValue<number>
    rangeEnd: SharedValue<number>
    position: SharedValue<number>
    ticks: readonly ScrubberTick[]
    /** The marks fade out while the range changes, and in again once they are placed for the new range. */
    marksShown: SharedValue<number>
    expanded: boolean
    leftLabel: string
    rightLabel: string
    onScrub: (seconds: number) => void
    onScrubEnd: (seconds: number, tick: ScrubberTick | null) => void
    onScrubStart?: () => void
    onScrubCancel: () => void
    /** The card on screen: its range and markers get timing marks in a measuring build. */
    measured?: boolean
}

const SNAP_POINTS = 12
const REST_HEIGHT = 3
const GROWN_HEIGHT = 8

export function FeedScrubber({
    start,
    end,
    position,
    ticks,
    expanded,
    leftLabel,
    rightLabel,
    rangeStart,
    rangeEnd,
    marksShown,
    onScrub,
    onScrubEnd,
    onScrubStart,
    onScrubCancel,
    measured = false,
}: FeedScrubberProps): ReactElement {
    const styles = useStyles()
    const width = useSharedValue(0)
    const touched = useSharedValue(0)
    const grown = useSharedValue(expanded ? 1 : 0)
    const scrubbing = useSharedValue(false)
    const scrubAt = useSharedValue(start)
    const snapped = useSharedValue(-1)
    const range = useDerivedValue(() => ({ start: rangeStart.value, end: rangeEnd.value }))
    const tickSeconds = useSharedValue<number[]>([])
    const [label, setLabel] = useState<string | null>(null)
    // biome-ignore lint/correctness/useExhaustiveDependencies: `measured` only gates a timing mark.
    useEffect(() => {
        if (measured) {
            perfMark('markersRendered', Date.now(), { count: ticks.length })
            requestAnimationFrame(() => perfMark('markersPainted', Date.now(), { count: ticks.length }))
        }
        tickSeconds.value = ticks.map((tick) => tick.seconds)
    }, [ticks, tickSeconds])
    useEffect(() => {
        grown.value = withTiming(expanded ? 1 : 0, { duration: 160 })
    }, [expanded, grown])

    const showLabel = useCallback(
        (seconds: number, tickIndex: number): void => {
            const tick = tickIndex >= 0 ? ticks[tickIndex] : undefined
            setLabel(tick ? `${formatOffset(tick.seconds * 1000)} · ${tick.label}` : formatOffset(seconds * 1000))
        },
        [ticks]
    )
    const finish = useCallback(
        (seconds: number, tickIndex: number): void => {
            setLabel(null)
            onScrubEnd(seconds, tickIndex >= 0 ? (ticks[tickIndex] ?? null) : null)
        },
        [onScrubEnd, ticks]
    )
    const cancel = useCallback((): void => {
        setLabel(null)
        onScrubCancel()
    }, [onScrubCancel])
    const begin = useCallback((): void => onScrubStart?.(), [onScrubStart])

    function secondsAt(x: number): number {
        'worklet'
        const { start: from, end: to } = range.value
        const span = Math.max(0.001, to - from)
        const fraction = width.value > 0 ? Math.min(1, Math.max(0, x / width.value)) : 0
        let seconds = from + fraction * span
        let nearest = -1
        let nearestDistance = SNAP_POINTS
        tickSeconds.value.forEach((tickSecondsValue, index) => {
            const distance = Math.abs(((tickSecondsValue - from) / span) * width.value - x)
            if (distance <= nearestDistance) {
                nearest = index
                nearestDistance = distance
            }
        })
        if (nearest >= 0) {
            seconds = tickSeconds.value[nearest] as number
        }
        if (nearest !== snapped.value) {
            snapped.value = nearest
            if (nearest >= 0) {
                scheduleOnRN(haptic, 'selection')
            }
        }
        return seconds
    }

    const pan = Gesture.Pan()
        .minDistance(0)
        .shouldCancelWhenOutside(false)
        .failOffsetY([-28, 28])
        .hitSlop({ top: 14, bottom: 10 })
        .onBegin((event) => {
            'worklet'
            touched.value = withTiming(1, { duration: 120 })
            scrubbing.value = true
            snapped.value = -1
            scheduleOnRN(begin)
            const seconds = secondsAt(event.x)
            scrubAt.value = seconds
        })
        .onUpdate((event) => {
            'worklet'
            const seconds = secondsAt(event.x)
            scrubAt.value = seconds
            scheduleOnRN(onScrub, seconds)
            scheduleOnRN(showLabel, seconds, snapped.value)
        })
        .onFinalize((event, success) => {
            'worklet'
            touched.value = withTiming(0, { duration: 200 })
            scrubbing.value = false
            // A vertical swipe that started on the bar pages the feed instead.
            if (!success || Math.abs(event.translationY) > 24) {
                scheduleOnRN(cancel)
                return
            }
            scheduleOnRN(finish, secondsAt(event.x), snapped.value)
        })

    const size = useDerivedValue(() => Math.max(touched.value, grown.value))
    const fraction = useDerivedValue(() => {
        const { start: from, end: to } = range.value
        const at = scrubbing.value ? scrubAt.value : position.value
        return Math.min(1, Math.max(0, (at - from) / Math.max(0.001, to - from)))
    })
    const trackStyle = useAnimatedStyle(() => ({
        height: interpolate(size.value, [0, 1], [REST_HEIGHT, GROWN_HEIGHT]),
    }))
    const fillStyle = useAnimatedStyle(() => ({ width: `${fraction.value * 100}%` }))
    const knobStyle = useAnimatedStyle(() => ({
        left: `${fraction.value * 100}%`,
        opacity: size.value,
        transform: [{ translateX: -7 }, { scale: interpolate(size.value, [0, 1], [0.4, 1]) }],
    }))
    const tickStyle = useAnimatedStyle(() => {
        const height = interpolate(size.value, [0, 1], [8, 14])
        const tickWidth = interpolate(size.value, [0, 1], [3, 4])
        return {
            height,
            width: tickWidth,
            transform: [{ translateX: -tickWidth / 2 }, { translateY: -height / 2 }],
        }
    })
    const labelsStyle = useAnimatedStyle(() => ({ opacity: size.value }))
    const marksStyle = useAnimatedStyle(() => ({ opacity: marksShown.value }))

    const onLayout = (event: LayoutChangeEvent): void => {
        width.value = event.nativeEvent.layout.width
    }
    const span = Math.max(0.001, end - start)

    return (
        <View style={styles.wrap} pointerEvents="box-none">
            <Animated.View style={[styles.labels, labelsStyle]} pointerEvents="none">
                <Text style={styles.time}>{leftLabel}</Text>
                {label !== null ? (
                    <Text style={styles.label} numberOfLines={1}>
                        {label}
                    </Text>
                ) : (
                    <LiveTime position={position} style={styles.label} />
                )}
                <Text style={styles.time}>{rightLabel}</Text>
            </Animated.View>
            <GestureDetector gesture={pan}>
                <View style={styles.hit} onLayout={onLayout} accessibilityRole="adjustable" accessibilityLabel="Seek">
                    <Animated.View style={[styles.track, trackStyle]}>
                        <Animated.View style={[styles.fill, fillStyle]} />
                    </Animated.View>
                    <Animated.View style={[styles.marks, marksStyle]} pointerEvents="none">
                        {ticks.map((tick) => (
                            <Animated.View
                                key={tick.key}
                                style={[
                                    styles.tick,
                                    tickStyle,
                                    {
                                        left: `${Math.min(100, Math.max(0, ((tick.seconds - start) / span) * 100))}%`,
                                        backgroundColor: tickColors[tick.kind],
                                    },
                                ]}
                            />
                        ))}
                    </Animated.View>
                    <Animated.View style={[styles.knob, knobStyle]} pointerEvents="none" />
                </View>
            </GestureDetector>
        </View>
    )
}

/**
 * The playhead time, kept out of the card's state: it re-renders this text once a second and nothing else, so the
 * card and its marks do not render on every time update.
 */
function LiveTime({ position, style }: { position: SharedValue<number>; style: object }): ReactElement {
    const [seconds, setSeconds] = useState(() => Math.floor(position.value))
    useAnimatedReaction(
        () => Math.floor(position.value),
        (now, previous) => {
            if (now !== previous) {
                scheduleOnRN(setSeconds, now)
            }
        }
    )
    return (
        <Text style={style} numberOfLines={1}>
            {formatOffset(seconds * 1000)}
        </Text>
    )
}

const useStyles = createStyles(() => ({
    wrap: {
        width: '100%',
    },
    labels: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        marginBottom: 2,
    },
    time: {
        fontFamily: fonts.mono,
        fontSize: 12,
        color: feedColors.textMuted,
        ...feedTextShadow,
    },
    label: {
        flex: 1,
        textAlign: 'center',
        fontSize: 13,
        fontWeight: '600',
        color: feedColors.text,
        ...feedTextShadow,
    },
    hit: {
        height: 28,
        justifyContent: 'center',
    },
    track: {
        width: '100%',
        borderRadius: 4,
        backgroundColor: feedColors.track,
        overflow: 'hidden',
    },
    fill: {
        height: '100%',
        backgroundColor: feedColors.fill,
        borderRadius: 4,
    },
    marks: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
    },
    tick: {
        position: 'absolute',
        top: '50%',
        borderRadius: 2,
    },
    knob: {
        position: 'absolute',
        width: 14,
        height: 14,
        borderRadius: 7,
        backgroundColor: feedColors.fill,
        top: 7,
        shadowColor: '#000',
        shadowOpacity: 0.35,
        shadowRadius: 4,
        shadowOffset: { width: 0, height: 1 },
    },
}))
