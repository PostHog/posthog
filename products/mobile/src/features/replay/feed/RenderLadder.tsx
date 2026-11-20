import { type ReactElement, useEffect, useState } from 'react'
import { ActivityIndicator, Text, View } from 'react-native'
import Animated, { FadeIn, FadeOut } from 'react-native-reanimated'

import { ChevronRightIcon } from '@/ui/icons/ChevronRightIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'

import { formatOffset } from '../sessionAdapters'
import { feedColors } from './feedStyle'

export type LadderState =
    | { kind: 'waiting' }
    | { kind: 'preparing'; clip: boolean; startedAt: number }
    | { kind: 'limit'; message: string }
    | { kind: 'failed'; message: string }
    | { kind: 'recording'; shownSeconds: number }

interface RenderLadderProps {
    state: LadderState
    onPlay: () => void
    onRetry: () => void
    onOpenWeb: (() => void) | null
    onCheckAgain: () => void
    nextReady: { title: string; onPress: () => void } | null
}

function useElapsed(startedAt: number): string {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        const timer = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(timer)
    }, [])
    return formatOffset(Math.max(0, now - startedAt))
}

export function RenderLadder({
    state,
    onPlay,
    onRetry,
    onOpenWeb,
    onCheckAgain,
    nextReady,
}: RenderLadderProps): ReactElement {
    const styles = useStyles()
    return (
        <Animated.View
            entering={FadeIn.duration(180)}
            exiting={FadeOut.duration(180)}
            style={styles.center}
            pointerEvents="box-none"
        >
            {state.kind === 'waiting' ? (
                <Pressable44
                    onPress={onPlay}
                    accessibilityLabel="Play"
                    style={styles.play}
                    pressedStyle={styles.playPressed}
                    testID="feed-ladder-play"
                >
                    <PlayIcon size={26} color={feedColors.text} />
                </Pressable44>
            ) : null}
            {state.kind === 'preparing' ? (
                <View style={styles.card} testID="feed-ladder-preparing">
                    <View style={styles.cardRow}>
                        <ActivityIndicator size="small" color={feedColors.text} />
                        <Text style={styles.chipText}>
                            {`${state.clip ? 'Preparing clip' : 'Preparing video'} · `}
                            <PreparingClock startedAt={state.startedAt} />
                        </Text>
                    </View>
                    <Text style={styles.cardNote}>
                        {state.clip
                            ? 'A moment takes about 10 seconds.'
                            : 'A whole session takes a few minutes. Moments are ready sooner.'}
                    </Text>
                </View>
            ) : null}
            {state.kind === 'recording' ? (
                <View style={styles.card} testID="feed-ladder-recording">
                    <View style={styles.cardRow}>
                        <View style={styles.liveDot} />
                        <Text style={styles.chipText}>Still recording</Text>
                    </View>
                    <Text style={styles.cardNote}>
                        {`Recorded up to ${formatOffset(state.shownSeconds * 1000)} so far. It plays here once it ends, and autoplay skips it.`}
                    </Text>
                    <Pressable44 onPress={onCheckAgain} accessibilityLabel="Check again" style={styles.action}>
                        <Text style={styles.actionText}>Check again</Text>
                    </Pressable44>
                </View>
            ) : null}
            {state.kind === 'limit' || state.kind === 'failed' ? (
                <View style={styles.panel} testID={state.kind === 'limit' ? 'feed-ladder-limit' : 'feed-ladder-failed'}>
                    <WarningIcon size={22} color={feedColors.text} />
                    <Text style={styles.panelTitle}>Couldn't play this recording</Text>
                    <Text style={styles.panelText}>{state.message}</Text>
                    <View style={styles.panelActions}>
                        {state.kind === 'failed' ? (
                            <Pressable44 onPress={onRetry} accessibilityLabel="Try again" style={styles.action}>
                                <Text style={styles.actionText}>Try again</Text>
                            </Pressable44>
                        ) : null}
                        {onOpenWeb ? (
                            <Pressable44 onPress={onOpenWeb} accessibilityLabel="Open in PostHog" style={styles.action}>
                                <Text style={styles.actionText}>Open in PostHog</Text>
                            </Pressable44>
                        ) : null}
                    </View>
                </View>
            ) : null}
            {nextReady && state.kind !== 'waiting' ? (
                <Pressable44
                    onPress={nextReady.onPress}
                    accessibilityLabel={`Ready: ${nextReady.title}`}
                    style={styles.ready}
                    testID="feed-ladder-next-ready"
                >
                    <Text style={styles.readyText} numberOfLines={1}>
                        {`Ready: ${nextReady.title}`}
                    </Text>
                    <ChevronRightIcon size={14} color={feedColors.text} />
                </Pressable44>
            ) : null}
        </Animated.View>
    )
}

function PreparingClock({ startedAt }: { startedAt: number }): ReactElement {
    return <>{useElapsed(startedAt)}</>
}

const useStyles = createStyles(() => ({
    center: {
        ...{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: 28,
        gap: 10,
    },
    play: {
        width: 68,
        height: 68,
        borderRadius: 34,
        alignItems: 'center',
        justifyContent: 'center',
        paddingLeft: 4,
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
    },
    playPressed: {
        backgroundColor: feedColors.glassPressed,
    },
    chip: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        height: 40,
        paddingHorizontal: 16,
        borderRadius: 20,
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
    },
    chipText: {
        fontSize: 15,
        fontWeight: '600',
        color: feedColors.text,
        fontVariant: ['tabular-nums'],
    },
    card: {
        alignItems: 'center',
        gap: 6,
        paddingVertical: 12,
        paddingHorizontal: 18,
        borderRadius: 20,
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
        maxWidth: 300,
    },
    cardRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
    },
    cardNote: {
        fontSize: 13,
        lineHeight: 18,
        color: feedColors.textMuted,
        textAlign: 'center',
    },
    liveDot: {
        width: 8,
        height: 8,
        borderRadius: 4,
        backgroundColor: feedColors.error,
    },
    panel: {
        alignItems: 'center',
        gap: 8,
        padding: 18,
        borderRadius: 22,
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
        maxWidth: 320,
    },
    panelTitle: {
        fontSize: 16,
        fontWeight: '700',
        color: feedColors.text,
        textAlign: 'center',
    },
    panelText: {
        fontSize: 14,
        lineHeight: 19,
        color: feedColors.textMuted,
        textAlign: 'center',
    },
    panelActions: {
        flexDirection: 'row',
        gap: 10,
        marginTop: 4,
    },
    action: {
        height: 38,
        paddingHorizontal: 16,
        borderRadius: 19,
        justifyContent: 'center',
        backgroundColor: 'rgba(255,255,255,0.16)',
    },
    actionText: {
        fontSize: 15,
        fontWeight: '600',
        color: feedColors.text,
    },
    ready: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 4,
        height: 34,
        maxWidth: 300,
        paddingHorizontal: 14,
        borderRadius: 17,
        backgroundColor: feedColors.glass,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
        marginTop: 4,
    },
    readyText: {
        flexShrink: 1,
        fontSize: 13,
        fontWeight: '600',
        color: feedColors.text,
    },
}))
