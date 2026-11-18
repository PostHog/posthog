import { type ReactElement, useEffect } from 'react'
import { Text, View } from 'react-native'
import Animated, {
    cancelAnimation,
    Easing,
    FadeIn,
    FadeOut,
    useAnimatedProps,
    useReducedMotion,
    useSharedValue,
    withTiming,
} from 'react-native-reanimated'
import Svg, { Circle } from 'react-native-svg'
import { scheduleOnRN } from 'react-native-worklets'

import { PlayIcon } from '@/ui/icons/PlayIcon'
import { RefreshIcon } from '@/ui/icons/RefreshIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'

import { compactDuration } from './feedAdapters'
import { feedColors } from './feedStyle'

const AnimatedCircle = Animated.createAnimatedComponent(Circle)

export const UP_NEXT_COUNTDOWN_MS = 3000
const RING = 64
const STROKE = 3
const RADIUS = (RING - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

interface UpNextCardProps {
    next: { title: string; person: string; durationSeconds: number } | null
    countdown: boolean
    onPlay: () => void
    onCancel: () => void
    onReplay: () => void
}

export function UpNextCard({ next, countdown, onPlay, onCancel, onReplay }: UpNextCardProps): ReactElement {
    const styles = useStyles()
    const reduceMotion = useReducedMotion()
    const progress = useSharedValue(0)

    useEffect(() => {
        if (!next || !countdown) {
            return undefined
        }
        progress.value = 0
        if (reduceMotion) {
            const timer = setTimeout(onPlay, UP_NEXT_COUNTDOWN_MS)
            return () => clearTimeout(timer)
        }
        progress.value = withTiming(1, { duration: UP_NEXT_COUNTDOWN_MS, easing: Easing.linear }, (finished) => {
            if (finished) {
                scheduleOnRN(onPlay)
            }
        })
        return () => cancelAnimation(progress)
    }, [next, countdown, onPlay, progress, reduceMotion])

    const ringProps = useAnimatedProps(() => ({ strokeDashoffset: CIRCUMFERENCE * (1 - progress.value) }))

    return (
        <Animated.View entering={FadeIn.duration(180)} exiting={FadeOut.duration(140)} style={styles.card}>
            {next ? (
                <>
                    <Pressable44
                        onPress={onPlay}
                        accessibilityLabel={`Play next: ${next.title}`}
                        style={styles.ring}
                        testID="feed-up-next-play"
                    >
                        <Svg width={RING} height={RING} style={styles.ringSvg}>
                            <Circle
                                cx={RING / 2}
                                cy={RING / 2}
                                r={RADIUS}
                                stroke={feedColors.track}
                                strokeWidth={STROKE}
                                fill="none"
                            />
                            {countdown ? (
                                <AnimatedCircle
                                    cx={RING / 2}
                                    cy={RING / 2}
                                    r={RADIUS}
                                    stroke={feedColors.text}
                                    strokeWidth={STROKE}
                                    strokeLinecap="round"
                                    fill="none"
                                    strokeDasharray={`${CIRCUMFERENCE} ${CIRCUMFERENCE}`}
                                    animatedProps={ringProps}
                                    transform={`rotate(-90 ${RING / 2} ${RING / 2})`}
                                />
                            ) : null}
                        </Svg>
                        <PlayIcon size={22} color={feedColors.text} />
                    </Pressable44>
                    <Text style={styles.eyebrow}>UP NEXT</Text>
                    <Text style={styles.title} numberOfLines={2}>
                        {next.title}
                    </Text>
                    <Text style={styles.meta} numberOfLines={1}>
                        {`${next.person} · ${compactDuration(next.durationSeconds)}`}
                    </Text>
                    <View style={styles.actions}>
                        <Pressable44
                            onPress={onReplay}
                            accessibilityLabel="Replay"
                            style={styles.pill}
                            pressedStyle={styles.pillPressed}
                            testID="feed-up-next-replay"
                        >
                            <RefreshIcon size={16} color={feedColors.text} />
                            <Text style={styles.pillText}>Replay</Text>
                        </Pressable44>
                        {countdown ? (
                            <Pressable44
                                onPress={onCancel}
                                accessibilityLabel="Cancel"
                                style={styles.pill}
                                pressedStyle={styles.pillPressed}
                                testID="feed-up-next-cancel"
                            >
                                <Text style={styles.pillText}>Cancel</Text>
                            </Pressable44>
                        ) : null}
                    </View>
                </>
            ) : (
                <>
                    <Text style={styles.title}>You're caught up</Text>
                    <Text style={styles.meta}>Pull down on the first recording to check for new ones.</Text>
                    <View style={styles.actions}>
                        <Pressable44 onPress={onReplay} accessibilityLabel="Replay" style={styles.pill}>
                            <RefreshIcon size={16} color={feedColors.text} />
                            <Text style={styles.pillText}>Replay</Text>
                        </Pressable44>
                    </View>
                </>
            )}
        </Animated.View>
    )
}

const useStyles = createStyles(() => ({
    card: {
        alignItems: 'center',
        paddingVertical: 22,
        paddingHorizontal: 22,
        borderRadius: 28,
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
        width: 280,
    },
    ring: {
        width: RING,
        height: RING,
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 14,
    },
    ringSvg: {
        position: 'absolute',
    },
    eyebrow: {
        fontSize: 11,
        fontWeight: '700',
        letterSpacing: 1,
        color: feedColors.textFaint,
        marginBottom: 4,
    },
    title: {
        fontSize: 17,
        fontWeight: '700',
        lineHeight: 22,
        color: feedColors.text,
        textAlign: 'center',
    },
    meta: {
        marginTop: 4,
        fontSize: 13,
        color: feedColors.textMuted,
        textAlign: 'center',
    },
    actions: {
        marginTop: 16,
        flexDirection: 'row',
        gap: 10,
    },
    pill: {
        height: 40,
        paddingHorizontal: 16,
        borderRadius: 20,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        backgroundColor: 'rgba(255,255,255,0.14)',
    },
    pillPressed: {
        backgroundColor: feedColors.glassPressed,
    },
    pillText: {
        fontSize: 15,
        fontWeight: '600',
        color: feedColors.text,
    },
}))
