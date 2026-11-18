import { useFocusEffect, useRouter } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, FlatList, type LayoutChangeEvent, Linking, RefreshControl, Text, View } from 'react-native'

import { RECORDING_OBJECT_TYPE } from '@/features/chat/objectContext'
import { HeaderMenu } from '@/features/views/screen/HeaderMenu'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { formatMonthDay } from '@/lib/dates'
import { safeHttpsUrl } from '@/lib/urls'
import { ChevronDownIcon } from '@/ui/icons/ChevronDownIcon'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { MoreIcon } from '@/ui/icons/MoreIcon'
import { RowsIcon } from '@/ui/icons/RowsIcon'
import { SettingsIcon } from '@/ui/icons/SettingsIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { useReplayContext } from '../hooks'
import { trackFullReplayOpened, trackSessionChatOpened } from '../replayAnalytics'
import { sessionWebUrl } from '../replayLinks'
import { FeedCard, type FeedCardHandle, itemTitle } from './FeedCard'
import { FeedInfoSheet, FeedSettingsSheet, FeedSourceSheet, SOURCE_LABELS } from './FeedSheets'
import { hasReadyVideo } from './feedAdapters'
import {
    trackFeedAutoAdvanced,
    trackFeedInfoOpened,
    trackFeedOpened,
    trackFeedSourceChanged,
    trackFeedUnitChanged,
} from './feedAnalytics'
import type { FeedItem, FeedSettings, FeedSource, FeedTimeline, FeedUnit } from './feedModel'
import { useFeedSettings } from './feedSettingsStore'
import { feedColors } from './feedStyle'
import { readyJobFor, useRenderQueue } from './renderQueue'
import { useFeed } from './useFeed'
import { type PoolSource, usePlayerPool } from './usePlayerPool'

const READY_LOOKAHEAD = 3

export function ReplayFeedScreen(): ReactElement {
    return (
        <OverlayHost>
            <FeedContent />
        </OverlayHost>
    )
}

function FeedContent(): ReactElement {
    const styles = useStyles()
    const back = useViewBack()
    const router = useRouter()
    const insets = useScreenInsets()
    const { mode, access, scope } = useReplayContext()
    const { unit, source, speed, autoplayNext, startAt, leadInSeconds, momentSeconds, phoneFit, set } =
        useFeedSettings()
    const settings = useMemo(
        (): FeedSettings => ({ speed, autoplayNext, startAt, leadInSeconds, momentSeconds, phoneFit }),
        [speed, autoplayNext, startAt, leadInSeconds, momentSeconds, phoneFit]
    )
    const feed = useFeed(source)
    const items = feed.items
    const jobs = useRenderQueue((state) => state.jobs)

    const [size, setSize] = useState<{ width: number; height: number } | null>(null)
    const onLayout = (event: LayoutChangeEvent): void => {
        const { width, height } = event.nativeEvent.layout
        setSize((previous) => (previous?.width === width && previous.height === height ? previous : { width, height }))
    }
    const [current, setCurrent] = useState(0)
    const [focused, setFocused] = useState(true)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )

    const [sources, setSources] = useState<ReadonlyMap<number, PoolSource>>(() => new Map())
    const onSource = useCallback((index: number, next: PoolSource | null): void => {
        setSources((previous) => {
            if (previous.get(index)?.key === next?.key) {
                return previous
            }
            const map = new Map(previous)
            if (next) {
                map.set(index, next)
            } else {
                map.delete(index)
            }
            return map
        })
    }, [])
    const pool = usePlayerPool(sources, current)

    const handles = useRef(new Map<number, FeedCardHandle>())
    const registerHandle = useCallback((index: number, handle: FeedCardHandle | null): void => {
        if (handle) {
            handles.current.set(index, handle)
        } else {
            handles.current.delete(index)
        }
    }, [])

    // biome-ignore lint/correctness/useExhaustiveDependencies: one event per open.
    useEffect(() => {
        trackFeedOpened({ source, unit })
    }, [])

    const listRef = useRef<FlatList<FeedItem>>(null)
    const scrollTo = useCallback(
        (index: number): void => {
            if (!size) {
                return
            }
            listRef.current?.scrollToOffset({ offset: index * size.height, animated: true })
            setCurrent(index)
        },
        [size]
    )

    const isReady = useCallback(
        (item: FeedItem): boolean =>
            hasReadyVideo(item.exports) || readyJobFor(jobs, item.recording.sessionId) !== null,
        [jobs]
    )
    const advanceTarget = useCallback(
        (index: number): number | null => {
            if (!items) {
                return null
            }
            const candidates: number[] = []
            for (let position = index + 1; position < items.length; position += 1) {
                if (!(items[position] as FeedItem).recording.ongoing) {
                    candidates.push(position)
                }
            }
            const ready = candidates.slice(0, READY_LOOKAHEAD).find((position) => isReady(items[position] as FeedItem))
            return ready ?? candidates[0] ?? null
        },
        [items, isReady]
    )
    const onAdvance = useCallback(
        (index: number): void => {
            const target = advanceTarget(index)
            if (target === null || !items) {
                return
            }
            trackFeedAutoAdvanced({
                sessionId: (items[index] as FeedItem).recording.sessionId,
                to: 'session',
                skipped: target - index - 1,
            })
            scrollTo(target)
        },
        [advanceTarget, items, scrollTo]
    )

    const viewabilityConfig = useRef({ itemVisiblePercentThreshold: 70 }).current
    const onViewableItemsChanged = useRef(
        ({ viewableItems }: { viewableItems: { index?: number | null; isViewable: boolean }[] }) => {
            const first = viewableItems.find((token) => token.isViewable && typeof token.index === 'number')
            if (typeof first?.index === 'number') {
                setCurrent(first.index)
            }
        }
    ).current

    const [sourceOpen, setSourceOpen] = useState(false)
    const [settingsOpen, setSettingsOpen] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)
    const [info, setInfo] = useState<{ item: FeedItem; timeline: FeedTimeline | null } | null>(null)

    const changeSource = (next: FeedSource): void => {
        if (next === source) {
            return
        }
        trackFeedSourceChanged(next)
        set({ source: next })
        setSources(new Map())
        setCurrent(0)
        listRef.current?.scrollToOffset({ offset: 0, animated: false })
    }
    const changeUnit = useCallback(
        (next: FeedUnit): void => {
            trackFeedUnitChanged(next)
            set({ unit: next })
        },
        [set]
    )
    const openSpeed = useCallback(() => setSettingsOpen(true), [])
    const openChat = useCallback(
        (item: FeedItem): void => {
            const { sessionId, personLabel, startedAt } = item.recording
            trackSessionChatOpened(sessionId)
            const date = startedAt ? ` · ${formatMonthDay(new Date(startedAt))}` : ''
            router.push({
                pathname: '/chat',
                params: {
                    entry: 'replay',
                    objectType: RECORDING_OBJECT_TYPE,
                    objectId: sessionId,
                    objectLabel: `${personLabel}${date}`,
                },
            })
        },
        [router]
    )
    const webUrlFor = useCallback(
        (item: FeedItem, seconds: number): string | undefined => {
            const url = sessionWebUrl(scope, item.recording.sessionId, seconds)
            return url ? safeHttpsUrl(url) : undefined
        },
        [scope]
    )
    const openWeb = useCallback(
        (item: FeedItem, seconds: number): void => {
            const url = webUrlFor(item, seconds)
            if (url) {
                trackFullReplayOpened(item.recording.sessionId)
                Linking.openURL(url).catch(() => undefined)
            }
        },
        [webUrlFor]
    )
    const openInfo = useCallback((item: FeedItem, timeline: FeedTimeline | null): void => {
        trackFeedInfoOpened(item.recording.sessionId)
        setInfo({ item, timeline })
    }, [])

    const { refresh } = feed
    const recheck = useCallback((): void => void refresh(), [refresh])
    const currentItem = items?.[current] ?? null
    const renderItem = ({ item, index }: { item: FeedItem; index: number }): ReactElement => {
        const target = advanceTarget(index)
        let nextReady: { index: number; title: string } | null = null
        if (items) {
            for (let position = index + 1; position < items.length; position += 1) {
                const candidate = items[position] as FeedItem
                if (!candidate.recording.ongoing && isReady(candidate)) {
                    nextReady = { index: position, title: itemTitle(candidate) }
                    break
                }
            }
        }
        return (
            <FeedCard
                item={item}
                index={index}
                width={size?.width ?? 0}
                height={size?.height ?? 0}
                insets={insets}
                active={focused && index === current}
                near={Math.abs(index - current) <= 2}
                pool={pool.get(index) ?? null}
                unit={unit}
                source={source}
                settings={settings}
                next={target === null ? null : (items?.[target] ?? null)}
                nextReady={nextReady}
                onSource={onSource}
                onAdvance={onAdvance}
                onJumpTo={scrollTo}
                onUnit={changeUnit}
                onSpeed={openSpeed}
                onChat={openChat}
                onInfo={openInfo}
                onOpenWeb={openWeb}
                onRecheck={recheck}
                registerHandle={registerHandle}
            />
        )
    }

    let body: ReactElement
    if (mode === 'demo') {
        body = (
            <FeedState
                title="Sessions aren't in the demo"
                message="Sign in to your PostHog project to see its recordings."
            />
        )
    } else if (access.state !== 'ok') {
        body = (
            <View style={styles.reauth}>
                <ViewsReauthState access={access} feature="replay" />
            </View>
        )
    } else if (feed.error && !items) {
        body = (
            <FeedState
                title="Couldn't load your sessions"
                message="Check your connection and try again."
                actionLabel="Try again"
                onAction={feed.retry}
            />
        )
    } else if (!items || !size) {
        body = <FeedSkeleton />
    } else if (items.length === 0) {
        body = (
            <FeedState
                title={
                    source === 'newest'
                        ? 'No finished recordings yet'
                        : `No sessions with ${SOURCE_LABELS[source].toLowerCase()}`
                }
                message={
                    source === 'newest'
                        ? feed.stillRecording > 0
                            ? `${feed.stillRecording} sessions are still recording. They show here once they end.`
                            : 'Recordings from the last 7 days show here once they end.'
                        : 'Nothing in the last 7 days. That is good news.'
                }
                actionLabel={source === 'newest' ? 'Refresh' : 'Show newest'}
                onAction={source === 'newest' ? () => void feed.refresh() : () => changeSource('newest')}
            />
        )
    } else {
        body = (
            <FlatList
                ref={listRef}
                data={items}
                keyExtractor={(item) => item.recording.sessionId}
                renderItem={renderItem}
                extraData={[current, pool, settings, unit, focused, jobs, size, insets]}
                pagingEnabled
                // A tap on the status bar would jump back to the first card mid-watch.
                scrollsToTop={false}
                decelerationRate="fast"
                showsVerticalScrollIndicator={false}
                getItemLayout={(_data, index) => ({ length: size.height, offset: size.height * index, index })}
                windowSize={5}
                initialNumToRender={2}
                maxToRenderPerBatch={2}
                removeClippedSubviews={false}
                viewabilityConfig={viewabilityConfig}
                onViewableItemsChanged={onViewableItemsChanged}
                onEndReached={feed.loadMore}
                onEndReachedThreshold={2}
                refreshControl={
                    <RefreshControl
                        refreshing={feed.refreshing}
                        onRefresh={() => void feed.refresh()}
                        tintColor={feedColors.text}
                    />
                }
                testID="feed-list"
            />
        )
    }

    return (
        <View style={styles.screen} onLayout={onLayout}>
            <StatusBar style="light" />
            {body}
            <View style={[styles.chrome, { top: insets.top + 4 }]} pointerEvents="box-none">
                <Pressable44
                    onPress={back}
                    accessibilityLabel="Back"
                    style={styles.backChip}
                    pressedStyle={styles.pressed}
                    testID="feed-back"
                >
                    <ChevronLeftIcon size={20} color={feedColors.text} />
                    <Text style={styles.chipText}>Back</Text>
                </Pressable44>
                <Pressable44
                    onPress={() => setSourceOpen(true)}
                    accessibilityLabel={`Show: ${SOURCE_LABELS[source]}`}
                    style={styles.sourcePill}
                    pressedStyle={styles.pressed}
                    testID="feed-source"
                >
                    <Text style={styles.chipText}>{SOURCE_LABELS[source]}</Text>
                    <ChevronDownIcon size={13} color={feedColors.text} />
                </Pressable44>
                <Pressable44
                    onPress={() => setMenuOpen(true)}
                    accessibilityLabel="More"
                    style={styles.morePill}
                    pressedStyle={styles.pressed}
                    testID="feed-more"
                >
                    <MoreIcon size={22} color={feedColors.text} />
                </Pressable44>
            </View>
            <HeaderMenu
                visible={menuOpen}
                onClose={() => setMenuOpen(false)}
                testID="feed-menu"
                items={[
                    {
                        key: 'list',
                        label: 'List',
                        Icon: RowsIcon,
                        onPress: () => router.push({ pathname: '/(stack)/replay', params: { view: 'list' } }),
                    },
                    { key: 'playback', label: 'Playback', Icon: SettingsIcon, onPress: () => setSettingsOpen(true) },
                    {
                        key: 'web',
                        label: 'Open in PostHog',
                        Icon: ExternalLinkIcon,
                        disabled: !currentItem || !webUrlFor(currentItem, 0),
                        onPress: () => currentItem && openWeb(currentItem, 0),
                    },
                ]}
            />
            <FeedSourceSheet
                visible={sourceOpen}
                source={source}
                onSelect={changeSource}
                onClose={() => setSourceOpen(false)}
            />
            <FeedSettingsSheet
                visible={settingsOpen}
                settings={settings}
                onChange={set}
                onClose={() => setSettingsOpen(false)}
            />
            <FeedInfoSheet
                visible={info !== null}
                item={info?.item ?? null}
                timeline={info?.timeline ?? null}
                onSeek={(seconds) => handles.current.get(current)?.seekToSession(seconds)}
                onOpenWeb={info && webUrlFor(info.item, 0) ? () => openWeb(info.item, 0) : null}
                onClose={() => setInfo(null)}
            />
        </View>
    )
}

interface FeedStateProps {
    title: string
    message: string
    actionLabel?: string
    onAction?: () => void
}

function FeedState({ title, message, actionLabel, onAction }: FeedStateProps): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.state} testID="feed-state">
            <Text style={styles.stateTitle}>{title}</Text>
            <Text style={styles.stateText}>{message}</Text>
            {actionLabel && onAction ? (
                <Pressable44 onPress={onAction} accessibilityLabel={actionLabel} style={styles.stateAction}>
                    <Text style={styles.chipText}>{actionLabel}</Text>
                </Pressable44>
            ) : null}
        </View>
    )
}

function FeedSkeleton(): ReactElement {
    const styles = useStyles()
    return (
        <View style={styles.skeleton} testID="feed-loading">
            <View style={styles.skeletonVideo}>
                <ActivityIndicator color={feedColors.textMuted} />
            </View>
            <View style={styles.skeletonCaption}>
                <View style={[styles.skeletonLine, { width: '38%' }]} />
                <View style={[styles.skeletonLine, styles.skeletonTitle, { width: '82%' }]} />
                <View style={[styles.skeletonLine, styles.skeletonTitle, { width: '64%' }]} />
                <View style={[styles.skeletonLine, { width: '52%' }]} />
            </View>
        </View>
    )
}

const glassPill = {
    height: 44,
    borderRadius: 22,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    backgroundColor: feedColors.glass,
    borderWidth: 1,
    borderColor: feedColors.glassBorder,
}

const useStyles = createStyles(() => ({
    screen: {
        flex: 1,
        backgroundColor: feedColors.stage,
    },
    reauth: {
        flex: 1,
        justifyContent: 'center',
    },
    chrome: {
        position: 'absolute',
        left: 12,
        right: 12,
        height: 44,
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    backChip: {
        ...glassPill,
        gap: 4,
        paddingLeft: 10,
        paddingRight: 14,
    },
    sourcePill: {
        ...glassPill,
        gap: 6,
        paddingHorizontal: 16,
    },
    morePill: {
        ...glassPill,
        width: 52,
        justifyContent: 'center',
    },
    pressed: {
        backgroundColor: feedColors.glassPressed,
    },
    chipText: {
        fontSize: 15,
        fontWeight: '600',
        color: feedColors.text,
    },
    state: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        alignItems: 'center',
        justifyContent: 'center',
        paddingHorizontal: 36,
        gap: 8,
    },
    stateTitle: {
        fontSize: 20,
        fontWeight: '700',
        color: feedColors.text,
        textAlign: 'center',
    },
    stateText: {
        fontSize: 15,
        lineHeight: 21,
        color: feedColors.textMuted,
        textAlign: 'center',
    },
    stateAction: {
        ...glassPill,
        marginTop: 10,
        paddingHorizontal: 18,
    },
    skeleton: {
        flex: 1,
        justifyContent: 'center',
    },
    skeletonVideo: {
        height: 250,
        backgroundColor: '#131418',
        alignItems: 'center',
        justifyContent: 'center',
        marginTop: -60,
    },
    skeletonCaption: {
        position: 'absolute',
        left: 16,
        right: 100,
        bottom: 96,
        gap: 9,
    },
    skeletonLine: {
        height: 12,
        borderRadius: 6,
        backgroundColor: '#24262C',
    },
    skeletonTitle: {
        height: 16,
    },
}))
