import { type ComponentType, memo, type ReactElement, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, FlatList, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, { type SharedValue, useAnimatedStyle, withTiming } from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ErrorTriangleIcon } from '@/ui/icons/ErrorTriangleIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { SparklesIcon } from '@/ui/icons/SparklesIcon'
import type { IconProps } from '@/ui/icons/types'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles, useColors } from '@/ui/theme'
import { radii, type } from '@/ui/tokens'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { SOURCE_LABELS } from './FeedSheets'
import { trackFeedPlayAll, trackFeedRowPlayed, trackFeedSessionsChip } from './feedAnalytics'
import { FEED_SOURCES, type FeedSource } from './feedModel'
import { SESSIONS_SLIDE_MS, sessionsCloses, sessionsDrag } from './feedPages'
import { type RowReason, type SessionRowModel, sessionRow } from './sessionRows'
import { useFeed, useSessionSignals } from './useFeed'

const REASON_ICONS: Record<RowReason, ComponentType<IconProps>> = {
    rage: FlagIcon,
    error: ErrorTriangleIcon,
    highlight: SparklesIcon,
    none: RecordingIcon,
}

const EMPTY: Record<FeedSource, string> = {
    highlights:
        'No highlights yet. Highlights come from Replay Vision, which ranks recordings and finds their key moments. Pick another source above.',
    rage: 'No recordings with rage clicks in the last 7 days. Pick another source above.',
    errors: 'No recordings with errors in the last 7 days. Pick another source above.',
    newest: 'No finished recordings in the last 7 days.',
}

interface FeedSourcesPageProps {
    /** 0 hidden to the right of the feed, 1 shown. The feed's swipe and this page's swipe both move it. */
    progress: SharedValue<number>
    /** The page mounts the first time it starts to show, then stays mounted. */
    mounted: boolean
    /** Shown or opening: the page takes touches. */
    open: boolean
    width: number
    /** The source the feed plays, which is the chip selected when the page opens. */
    playing: FeedSource
    /** The recording on screen in the feed, marked Playing in the list. */
    playingSession: string | null
    /** Plays `source` in the feed, from `sessionId` or from its first recording. */
    onPlay: (source: FeedSource, sessionId: string | null) => void
    onClose: () => void
}

/**
 * The page to the right of Full recording, where the feed's source is chosen. A chip changes only the list; Play all
 * and a row are the two ways to play. A swipe to the right anywhere on it goes back to the video.
 */
export function FeedSourcesPage({
    progress,
    mounted,
    open,
    width,
    playing,
    playingSession,
    onPlay,
    onClose,
}: FeedSourcesPageProps): ReactElement | null {
    const styles = useStyles()
    const colors = useColors()
    const insets = useScreenInsets()
    const [chip, setChip] = useState<FeedSource>(playing)
    useEffect(() => {
        if (open) {
            setChip(playing)
        }
    }, [open, playing])
    const closeRef = useRef(onClose)
    closeRef.current = onClose
    const slide = useAnimatedStyle(() => ({ transform: [{ translateX: (1 - progress.value) * width }] }))
    // Only a drag to the right starts it, and a vertical drag fails it first, so the list scrolls as usual.
    const swipeBack = useMemo(() => {
        const close = (): void => closeRef.current()
        return Gesture.Pan()
            .activeOffsetX(20)
            .failOffsetY([-12, 12])
            .onUpdate((event) => {
                'worklet'
                progress.value = sessionsDrag(event.translationX, width)
            })
            .onEnd((event, success) => {
                'worklet'
                if (success && sessionsCloses(event.translationX, event.velocityX)) {
                    progress.value = withTiming(0, { duration: SESSIONS_SLIDE_MS })
                    scheduleOnRN(close)
                } else {
                    progress.value = withTiming(1, { duration: 160 })
                }
            })
    }, [progress, width])
    if (!mounted || width <= 0) {
        return null
    }
    return (
        <GestureDetector gesture={swipeBack}>
            <Animated.View
                style={[StyleSheet.absoluteFill, styles.page, { paddingTop: insets.top + 4 }, slide]}
                pointerEvents={open ? 'auto' : 'none'}
                accessibilityElementsHidden={!open}
                importantForAccessibility={open ? 'auto' : 'no-hide-descendants'}
                accessibilityViewIsModal={open}
                testID="feed-sources"
            >
                <View style={styles.header}>
                    <Pressable44
                        onPress={onClose}
                        accessibilityLabel="Back to the feed"
                        style={styles.back}
                        pressedBackground={colors.pressed}
                        testID="feed-sources-back"
                    >
                        <ChevronLeftIcon size={20} color={colors.ink} />
                        <Text style={styles.backText}>Back</Text>
                    </Pressable44>
                </View>
                <Text style={styles.title}>Sessions</Text>
                <View style={styles.chips} accessibilityRole="tablist">
                    {FEED_SOURCES.map((source) => {
                        const selected = source === chip
                        return (
                            <Pressable44
                                key={source}
                                onPress={() => {
                                    if (!selected) {
                                        trackFeedSessionsChip(source)
                                        setChip(source)
                                    }
                                }}
                                accessibilityRole="tab"
                                accessibilityState={{ selected }}
                                accessibilityLabel={SOURCE_LABELS[source]}
                                style={[styles.chip, selected && styles.chipOn]}
                                pressedBackground={selected ? colors.ink : colors.pressed}
                                hitSlop={{ top: 6, bottom: 6, left: 2, right: 2 }}
                                testID={`feed-sources-chip-${source}`}
                            >
                                <Text style={[styles.chipText, selected && styles.chipTextOn]} numberOfLines={1}>
                                    {SOURCE_LABELS[source]}
                                </Text>
                            </Pressable44>
                        )
                    })}
                </View>
                <SessionsList
                    key={chip}
                    source={chip}
                    playingSession={playingSession}
                    bottomInset={insets.bottom}
                    onPlay={onPlay}
                />
            </Animated.View>
        </GestureDetector>
    )
}

interface SessionsListProps {
    source: FeedSource
    playingSession: string | null
    bottomInset: number
    onPlay: (source: FeedSource, sessionId: string | null) => void
}

/** The chosen source's recordings, from the query the feed plays: same time window, same skip of in-progress pages. */
function SessionsList({ source, playingSession, bottomInset, onPlay }: SessionsListProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const feed = useFeed(source)
    const items = feed.items
    const signals = useSessionSignals(items)
    // biome-ignore lint/correctness/useExhaustiveDependencies: the ages are as of when the rows arrived.
    const now = useMemo(() => new Date(), [items])
    const rows = useMemo(
        () =>
            (items ?? []).map((item) => ({
                item,
                model: sessionRow(item, signals.get(item.recording.sessionId), source, now),
            })),
        [items, signals, source, now]
    )

    if ((items === undefined && feed.error) || (rows.length === 0 && feed.pageError)) {
        return (
            <View style={styles.state} testID="feed-sources-error">
                <Text style={styles.stateText}>
                    Couldn't load these recordings. Check your connection and try again.
                </Text>
                <Pressable44
                    onPress={feed.pageError ? feed.retryMore : feed.retry}
                    accessibilityLabel="Try again"
                    style={styles.retry}
                    pressedBackground={colors.pressed}
                >
                    <Text style={styles.retryText}>Try again</Text>
                </Pressable44>
            </View>
        )
    }
    if (items === undefined) {
        return (
            <View style={styles.list} testID="feed-sources-loading" accessibilityLabel="Loading recordings">
                {[0, 1, 2, 3, 4].map((slot) => (
                    <View key={slot} style={[styles.row, styles.rowSkeleton]}>
                        <View style={[styles.rowIcon, styles.skeleton]} />
                        <View style={styles.rowBody}>
                            <View style={[styles.skeletonLine, { width: '72%' }]} />
                            <View style={[styles.skeletonLine, { width: '48%' }]} />
                            <View style={[styles.skeletonLine, { width: '60%' }]} />
                        </View>
                    </View>
                ))}
            </View>
        )
    }
    if (items.length === 0) {
        return (
            <View style={styles.state} testID="feed-sources-empty">
                <Text style={styles.stateText}>{EMPTY[source]}</Text>
            </View>
        )
    }
    return (
        <FlatList
            data={rows}
            keyExtractor={(row) => row.item.recording.sessionId}
            renderItem={({ item: row, index }) => (
                <SessionRow
                    model={row.model}
                    playing={row.item.recording.sessionId === playingSession}
                    onPress={() => {
                        trackFeedRowPlayed({ source, sessionId: row.item.recording.sessionId, position: index })
                        onPlay(source, row.item.recording.sessionId)
                    }}
                />
            )}
            ListHeaderComponent={
                <Pressable44
                    onPress={() => {
                        trackFeedPlayAll(source)
                        onPlay(source, null)
                    }}
                    accessibilityLabel={`Play all, ${SOURCE_LABELS[source]}`}
                    style={styles.playAll}
                    pressedStyle={styles.playAllPressed}
                    testID="feed-sources-play-all"
                >
                    <PlayIcon size={13} color={colors.onInk} />
                    <Text style={styles.playAllText}>{`Play all · ${SOURCE_LABELS[source]}`}</Text>
                </Pressable44>
            }
            ListFooterComponent={
                feed.loadingMore ? (
                    <ActivityIndicator style={styles.more} color={colors.secondary} />
                ) : feed.pageError ? (
                    <View style={styles.state}>
                        <Text style={styles.stateText}>Couldn't load more recordings.</Text>
                        <Pressable44
                            onPress={feed.retryMore}
                            style={styles.retry}
                            pressedBackground={colors.pressed}
                            testID="feed-sources-retry-more"
                        >
                            <Text style={styles.retryText}>Try again</Text>
                        </Pressable44>
                    </View>
                ) : undefined
            }
            onEndReached={feed.loadMore}
            onEndReachedThreshold={1.5}
            contentContainerStyle={[styles.list, { paddingBottom: bottomInset + 24 }]}
            testID={`feed-sources-list-${source}`}
        />
    )
}

interface SessionRowProps {
    model: SessionRowModel
    playing: boolean
    onPress: () => void
}

/** One recording, text first: why it is worth watching, who and how long, and where its problems sit. */
const SessionRow = memo(function SessionRow({ model, playing, onPress }: SessionRowProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const tint: Record<RowReason, string> = {
        rage: colors.orange,
        error: colors.diffRed,
        highlight: colors.purple,
        none: colors.secondary,
    }
    const Icon = REASON_ICONS[model.reason]
    return (
        <Pressable44
            onPress={onPress}
            accessibilityRole="button"
            accessibilityLabel={[
                `Play ${model.title}`,
                model.reasonText,
                `${model.person}, ${model.details}`,
                playing ? 'Playing' : null,
            ]
                .filter(Boolean)
                .join('. ')}
            style={styles.row}
            pressedBackground={colors.pressed}
            hitSlop={0}
        >
            <View style={[styles.rowIcon, { backgroundColor: colors.sunken }]}>
                <Icon size={15} color={tint[model.reason]} />
            </View>
            <View style={styles.rowBody}>
                <Text style={styles.rowTitle} numberOfLines={2}>
                    {model.title}
                </Text>
                {model.reasonText ? (
                    <Text style={[styles.reason, { color: tint[model.reason] }]} numberOfLines={1}>
                        {model.reasonText}
                    </Text>
                ) : null}
                <View style={styles.metaRow}>
                    <Text style={[styles.meta, styles.person]} numberOfLines={1}>
                        {model.person}
                    </Text>
                    <Text style={styles.meta}>{` · ${model.details}`}</Text>
                </View>
                <View style={styles.strip}>
                    {model.marks.map((mark) => (
                        <View
                            key={mark.key}
                            style={[
                                styles.stripMark,
                                {
                                    left: `${mark.at * 100}%`,
                                    backgroundColor: mark.kind === 'error' ? colors.diffRed : colors.orange,
                                },
                            ]}
                        />
                    ))}
                </View>
            </View>
            {playing ? (
                <View style={styles.playingChip}>
                    <Text style={styles.playingText}>Playing</Text>
                </View>
            ) : (
                <View style={styles.play}>
                    <PlayIcon size={11} color={colors.ink} />
                </View>
            )}
        </Pressable44>
    )
})

const useStyles = createStyles(({ colors }) => ({
    page: {
        flex: 1,
        backgroundColor: colors.background,
    },
    header: {
        height: 48,
        paddingHorizontal: 12,
        flexDirection: 'row',
        alignItems: 'center',
    },
    back: {
        height: 40,
        paddingLeft: 8,
        paddingRight: 14,
        borderRadius: radii.pill,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 2,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
    },
    backText: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    title: {
        ...type.screenTitle,
        color: colors.ink,
        marginTop: 6,
        marginHorizontal: 20,
    },
    chips: {
        flexDirection: 'row',
        gap: 6,
        marginTop: 14,
        marginHorizontal: 16,
    },
    chip: {
        flexGrow: 1,
        height: 36,
        paddingHorizontal: 10,
        borderRadius: radii.pill,
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.border,
    },
    chipOn: {
        backgroundColor: colors.ink,
        borderColor: colors.ink,
    },
    chipText: {
        ...type.metaSmall,
        fontWeight: '600',
        color: colors.ink,
    },
    chipTextOn: {
        color: colors.onInk,
    },
    list: {
        paddingHorizontal: 16,
        paddingTop: 14,
    },
    playAll: {
        height: 44,
        marginBottom: 10,
        borderRadius: radii.pill,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        backgroundColor: colors.ink,
    },
    playAllPressed: {
        backgroundColor: colors.inkHover,
    },
    playAllText: {
        ...type.bodySmallStrong,
        color: colors.onInk,
    },
    row: {
        flexDirection: 'row',
        alignItems: 'flex-start',
        gap: 12,
        paddingVertical: 12,
        paddingHorizontal: 12,
        marginBottom: 8,
        borderRadius: radii.card,
        backgroundColor: colors.surface,
        borderWidth: 1,
        borderColor: colors.hairline,
    },
    rowSkeleton: {
        height: 98,
    },
    rowIcon: {
        width: 30,
        height: 30,
        borderRadius: 15,
        alignItems: 'center',
        justifyContent: 'center',
    },
    rowBody: {
        flex: 1,
        gap: 3,
    },
    rowTitle: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    reason: {
        ...type.metaSmall,
        fontWeight: '600',
    },
    metaRow: {
        flexDirection: 'row',
    },
    meta: {
        ...type.meta,
        color: colors.secondary,
    },
    person: {
        flexShrink: 1,
    },
    playingChip: {
        height: 24,
        marginTop: 3,
        paddingHorizontal: 8,
        borderRadius: 12,
        justifyContent: 'center',
        backgroundColor: colors.pressed,
    },
    playingText: {
        ...type.meta,
        fontWeight: '600',
        color: colors.ink,
    },
    strip: {
        height: 4,
        marginTop: 6,
        borderRadius: 2,
        backgroundColor: colors.sunken,
        overflow: 'hidden',
    },
    stripMark: {
        position: 'absolute',
        top: 0,
        bottom: 0,
        width: 3,
        marginLeft: -1.5,
        borderRadius: 1.5,
    },
    play: {
        width: 28,
        height: 28,
        marginTop: 1,
        borderRadius: 14,
        alignItems: 'center',
        justifyContent: 'center',
        paddingLeft: 2,
        borderWidth: 1,
        borderColor: colors.border,
    },
    state: {
        paddingHorizontal: 24,
        paddingTop: 40,
        alignItems: 'center',
        gap: 14,
    },
    stateText: {
        ...type.bodySmall,
        color: colors.secondary,
        textAlign: 'center',
    },
    retry: {
        height: 40,
        paddingHorizontal: 18,
        borderRadius: radii.pill,
        justifyContent: 'center',
        borderWidth: 1,
        borderColor: colors.border,
    },
    retryText: {
        ...type.bodySmallStrong,
        color: colors.ink,
    },
    skeleton: {
        backgroundColor: colors.pressed,
    },
    skeletonLine: {
        height: 11,
        marginTop: 5,
        borderRadius: 5,
        backgroundColor: colors.pressed,
    },
    more: {
        marginVertical: 16,
    },
}))
