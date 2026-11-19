import { useQueries } from '@tanstack/react-query'
import * as Clipboard from 'expo-clipboard'
import { Stack, useFocusEffect, useRouter } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { type ReactElement, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
    ActivityIndicator,
    type LayoutChangeEvent,
    Linking,
    type NativeScrollEvent,
    type NativeSyntheticEvent,
    RefreshControl,
    type ScrollViewInstance,
    Text,
    View,
} from 'react-native'
import Animated, {
    interpolate,
    useAnimatedScrollHandler,
    useAnimatedStyle,
    useDerivedValue,
    useFrameCallback,
    useSharedValue,
    withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { RECORDING_OBJECT_TYPE } from '@/features/chat/objectContext'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { ViewsReauthState } from '@/features/views/ViewsReauthState'
import { formatMonthDay } from '@/lib/dates'
import { haptic } from '@/lib/haptics'
import { safeHttpsUrl } from '@/lib/urls'
import { ChevronLeftIcon } from '@/ui/icons/ChevronLeftIcon'
import { DashboardIcon } from '@/ui/icons/DashboardIcon'
import { OverlayHost } from '@/ui/OverlayPortal'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'
import { useScreenInsets } from '@/ui/useScreenInsets'

import { useReplayContext } from '../hooks'
import { trackFullReplayOpened, trackSessionChatOpened } from '../replayAnalytics'
import { sessionWebUrl } from '../replayLinks'
import type { SessionSummary } from '../replayModel'
import { formatOffset } from '../sessionAdapters'
import { FeedCard, type FeedCardHandle, type StartRequest, type UpNextInfo } from './FeedCard'
import { FeedInfoSheet, FeedSettingsSheet, FeedShareSheet, SOURCE_LABELS } from './FeedSheets'
import { FeedSourcesPage } from './FeedSourcesPage'
import { FeedTabs } from './FeedTabs'
import { feedMoments, hasReadyVideo, itemTitle } from './feedAdapters'
import {
    trackFeedAutoAdvanced,
    trackFeedInfoOpened,
    trackFeedNotInterested,
    trackFeedOpened,
    trackFeedShared,
    trackFeedSourceChanged,
    trackFeedSourcesOpened,
    trackFeedSpeedUnlocked,
    trackFeedUnitChanged,
} from './feedAnalytics'
import { buildFeedCards, type FeedCardEntry, type KeyOverride, nextCardIndex } from './feedCards'
import { resetFeedHold, unlockFeed, useFeedHold } from './feedHoldStore'
import {
    type FeedItem,
    type FeedSettings,
    type FeedSource,
    type FeedTimeline,
    type FeedUnit,
    MOMENT_WINDOW,
    type Moment,
} from './feedModel'
import { SESSIONS_SLIDE_MS } from './feedPages'
import { FEED_DEBUG, FEED_PERF, perfMark } from './feedPerf'
import { FEED_PLAYER_KIND } from './feedPlayerKind'
import { useFeedSettings } from './feedSettingsStore'
import { feedColors } from './feedStyle'
import { HoldHud } from './HoldHud'
import { readyJobFor, useRenderQueue } from './renderQueue'
import { feedTimelineQuery, useFeed } from './useFeed'
import { type PoolSource, usePlayerPool } from './usePlayerPool'
import { useWebPlayerPool } from './useWebPlayerPool'

const READY_LOOKAHEAD = 3
const EMPTY_TIMELINE: FeedTimeline = { events: [], browser: null, os: null, viewport: null }
/** Moments come from each recording's events, which load for the recordings around the one on screen. */
const TIMELINES_BEHIND = 2
const TIMELINES_AHEAD = 3
/** Cards this far from the current one are mounted; the rest of a long row of moments is empty space. */
const MOUNTED_CARDS = 2
/** The next page of recordings loads when the card on screen is this close to the last card. */
const LOAD_AHEAD = 4
/**
 * A tab switch renders the new mode after its animations end (the tab underline takes 220 ms and the range 260 ms), so
 * the list rebuild never runs while they move.
 */
const SWITCH_COMMIT_MS = 280

function emptyTitle(source: FeedSource): string {
    if (source === 'highlights') {
        return 'No highlights yet'
    }
    return source === 'newest'
        ? 'No finished recordings yet'
        : `No recordings with ${SOURCE_LABELS[source].toLowerCase()}`
}

function emptyMessage(source: FeedSource, stillRecording: number): string {
    if (source === 'highlights') {
        return 'Highlights come from Replay Vision, which ranks recordings and finds their key moments. Pick another source for now.'
    }
    if (source === 'newest') {
        return stillRecording > 0
            ? `${stillRecording} recordings are still in progress. They show here once they end.`
            : 'Recordings from the last 7 days show here once they end.'
    }
    return 'Nothing in the last 7 days.'
}
const NO_SOURCES: ReadonlyMap<number, PoolSource> = new Map()

/**
 * One row per recording, with its cards stacked inside it. The feed is a paged scroll view, not a virtualized list:
 * a virtualized list mounts rows by pixel window, and when the cards above the current one change count (a tab
 * switch, moments that load), it read the old offset once and unmounted the card on screen, which reloaded its page.
 * Rows are plain views, and only the cards near the current one mount.
 */
interface FeedRow {
    item: FeedItem
    cards: FeedCardEntry[]
}

function sessionOfKey(key: string): string {
    return key.slice(0, key.lastIndexOf(':'))
}

interface CachedMoments {
    timeline: FeedTimeline | undefined
    summary: SessionSummary | null
    source: FeedSource
    durationSeconds: number
    moments: Moment[]
}

export function ReplayFeedScreen(): ReactElement {
    const scope = useRenderQueue((state) => state.scope)
    return (
        <OverlayHost key={scope}>
            <FeedContent />
        </OverlayHost>
    )
}

function FeedContent(): ReactElement {
    const styles = useStyles()
    const back = useViewBack()
    const router = useRouter()
    const insets = useScreenInsets()
    const { mode, access, scope, ready } = useReplayContext()
    const demo = mode === 'demo'
    const webPlayer = demo || FEED_PLAYER_KIND === 'web'
    const { unit, source, speed, autoplayNext, skipInactivity, hidden, set, hide } = useFeedSettings()
    const settings = useMemo(
        (): FeedSettings => ({ speed, autoplayNext, skipInactivity }),
        [speed, autoplayNext, skipInactivity]
    )
    const feed = useFeed(source)
    const items = feed.items
    const holding = useFeedHold((state) => state.hold !== null)
    const lock = useFeedHold((state) => state.lock)
    // The lock lasts while the feed is open: it survives swipes, and leaving the feed ends it.
    useEffect(() => () => resetFeedHold(), [])
    const jobs = useRenderQueue((state) => state.jobs)

    const [size, setSize] = useState<{ width: number; height: number } | null>(null)
    const onLayout = (event: LayoutChangeEvent): void => {
        const { width, height } = event.nativeEvent.layout
        setSize((previous) => (previous?.width === width && previous.height === height ? previous : { width, height }))
    }
    const [focused, setFocused] = useState(true)
    useFocusEffect(
        useCallback(() => {
            setFocused(true)
            return () => setFocused(false)
        }, [])
    )

    // The card on screen, by key. Moments that load above it, or a tab switch, move its index but not the card.
    const [currentKey, setCurrentKey] = useState<string | null>(null)
    const focusSession = currentKey ? sessionOfKey(currentKey) : null
    const focusRow = items
        ? Math.max(
              0,
              items.findIndex((item) => item.recording.sessionId === focusSession)
          )
        : 0
    const windowItems = useMemo(
        () => items?.slice(Math.max(0, focusRow - TIMELINES_BEHIND), focusRow + TIMELINES_AHEAD + 1) ?? [],
        [items, focusRow]
    )
    const timelineQueries = useQueries({
        queries: windowItems.map((item) => feedTimelineQuery(scope, item, ready, demo)),
    })
    const retainedSessions = useMemo(() => new Set(items?.map((item) => item.recording.sessionId)), [items])
    const knownTimelines = useRef<ReadonlyMap<string, FeedTimeline>>(new Map())
    const timelinesVersion = timelineQueries.map((query) => query.dataUpdatedAt).join(',')
    // A recording keeps the events it loaded after it leaves the window, so its card count never shrinks back.
    // biome-ignore lint/correctness/useExhaustiveDependencies: the queries change when their version does.
    const timelines = useMemo((): ReadonlyMap<string, FeedTimeline> => {
        const next = new Map([...knownTimelines.current].filter(([id]) => retainedSessions.has(id)))
        timelineQueries.forEach((query, position) => {
            const sessionId = windowItems[position]?.recording.sessionId
            if (sessionId && query.data) {
                next.set(sessionId, query.data)
            }
        })
        knownTimelines.current = next
        return next
    }, [timelinesVersion, windowItems, retainedSessions])

    const momentCache = useRef(new Map<string, CachedMoments>())
    // Written in the same step as the unit, never apart from it. The unit lives in a store that renders at once, so
    // React state here would land one render later, and for that render the card on screen would get another key and
    // remount with a new page.
    const keyOverrides = useRef<ReadonlyMap<string, KeyOverride>>(new Map())
    const rows = useMemo((): FeedRow[] | undefined => {
        for (const id of momentCache.current.keys()) {
            if (!retainedSessions.has(id)) {
                momentCache.current.delete(id)
            }
        }
        if (!items) {
            return undefined
        }
        const momentsFor = (item: FeedItem): Moment[] => {
            const { sessionId, durationSeconds } = item.recording
            const timeline = timelines.get(sessionId)
            const cached = momentCache.current.get(sessionId)
            if (
                cached &&
                cached.timeline === timeline &&
                cached.summary === item.summary &&
                cached.source === source &&
                cached.durationSeconds === durationSeconds
            ) {
                return cached.moments
            }
            const moments = feedMoments(
                timeline ?? EMPTY_TIMELINE,
                item.summary,
                durationSeconds,
                MOMENT_WINDOW,
                source
            )
            momentCache.current.set(sessionId, { timeline, summary: item.summary, source, durationSeconds, moments })
            return moments
        }
        const grouped: FeedRow[] = []
        for (const card of buildFeedCards(items, unit, momentsFor, keyOverrides.current)) {
            const last = grouped.at(-1)
            if (last && last.item === card.item) {
                last.cards.push(card)
            } else {
                grouped.push({ item: card.item, cards: [card] })
            }
        }
        return grouped
    }, [items, unit, timelines, source, retainedSessions])
    const cards = useMemo(() => rows?.flatMap((row) => row.cards), [rows])
    const cardsRef = useRef(cards)
    cardsRef.current = cards

    const lastIndex = useRef(0)
    const currentIndex = useMemo((): number => {
        if (!cards || cards.length === 0) {
            return 0
        }
        const found = currentKey ? cards.findIndex((card) => card.key === currentKey) : -1
        return found >= 0 ? found : Math.min(lastIndex.current, cards.length - 1)
    }, [cards, currentKey])
    const currentCard = cards?.[currentIndex] ?? null

    const [sources, setSources] = useState<ReadonlyMap<number, PoolSource>>(() => new Map())
    const onSource = useCallback((index: number, next: PoolSource | null): void => {
        setSources((previous) => {
            const current = previous.get(index)
            if (current?.key === next?.key && current?.source === next?.source) {
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
    const videoPool = usePlayerPool(webPlayer ? NO_SOURCES : sources, currentIndex)
    const webPool = useWebPlayerPool(cards ?? null, currentIndex, webPlayer, demo)

    const handles = useRef(new Map<string, FeedCardHandle>())
    const registerHandle = useCallback((key: string, handle: FeedCardHandle | null): void => {
        if (handle) {
            handles.current.set(key, handle)
        } else {
            handles.current.delete(key)
        }
    }, [])

    // biome-ignore lint/correctness/useExhaustiveDependencies: one event per open.
    useEffect(() => {
        trackFeedOpened({ source, unit })
    }, [])

    // The list follows `currentIndex`: when cards above the current one change, it moves to the card's new place.
    // `listIndex` is the card the list shows, as this screen last moved it or saw it settle.
    const listRef = useRef<ScrollViewInstance | null>(null)
    const listIndex = useRef(0)
    const listHeight = useRef(0)
    const dragging = useRef(false)
    const setListRef = useCallback((list: ScrollViewInstance | null): void => {
        listRef.current = list
        if (!list) {
            listIndex.current = 0
            listHeight.current = 0
        }
    }, [])
    useLayoutEffect(() => {
        if (!cards || cards.length === 0) {
            return
        }
        lastIndex.current = currentIndex
        const key = cards[currentIndex]?.key ?? null
        if (key !== currentKey) {
            setCurrentKey(key)
        }
        if (size && !dragging.current && (listIndex.current !== currentIndex || listHeight.current !== size.height)) {
            listIndex.current = currentIndex
            listHeight.current = size.height
            listRef.current?.scrollTo({ y: currentIndex * size.height, animated: false })
        }
    }, [cards, currentIndex, currentKey, size])

    const { loadMore } = feed
    useEffect(() => {
        if (cards && cards.length - currentIndex <= LOAD_AHEAD) {
            loadMore()
        }
    }, [cards, currentIndex, loadMore])

    const scrollTo = useCallback(
        (index: number): void => {
            const target = cardsRef.current?.[index]
            if (!size || !target) {
                return
            }
            listIndex.current = index
            setCurrentKey(target.key)
            listRef.current?.scrollTo({ y: index * size.height, animated: true })
        },
        [size]
    )
    // The settled offset picks the current card, not the list's viewability callback. That callback can report the
    // card that was at the old offset when cards above the current one change, before the list moves.
    const onSettle = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>): void => {
        dragging.current = false
        const { contentOffset, layoutMeasurement } = event.nativeEvent
        const list = cardsRef.current
        if (!list || list.length === 0 || layoutMeasurement.height <= 0) {
            return
        }
        const index = Math.max(0, Math.min(list.length - 1, Math.round(contentOffset.y / layoutMeasurement.height)))
        listIndex.current = index
        setCurrentKey(list[index]?.key ?? null)
    }, [])
    const onDragEnd = useCallback(
        (event: NativeSyntheticEvent<NativeScrollEvent>): void => {
            const { contentOffset, layoutMeasurement } = event.nativeEvent
            const page = contentOffset.y / Math.max(1, layoutMeasurement.height)
            // A release that is already on a page has no momentum to wait for.
            if (Math.abs(page - Math.round(page)) < 0.01) {
                onSettle(event)
            }
        },
        [onSettle]
    )

    const scrollY = useSharedValue(0)
    const pageHeight = useSharedValue(0)
    useEffect(() => {
        pageHeight.value = size?.height ?? 0
    }, [size, pageHeight])
    const onScroll = useAnimatedScrollHandler((event) => {
        scrollY.value = event.contentOffset.y
    })
    // Between two pages the chrome dims to half, tied to the drag, and it is back in full once a page settles.
    const scrollFade = useDerivedValue(() => {
        const page = pageHeight.value
        if (page <= 0) {
            return 1
        }
        const off = Math.abs(scrollY.value - Math.round(scrollY.value / page) * page)
        return interpolate(off, [0, page * 0.12], [1, 0.5], 'clamp')
    })
    const holdShown = useSharedValue(1)
    useEffect(() => {
        holdShown.value = withTiming(holding ? 0 : 1, { duration: holding ? 120 : 180 })
    }, [holding, holdShown])
    const chromeStyle = useAnimatedStyle(() => ({ opacity: holdShown.value * scrollFade.value }))
    const tabProgress = useSharedValue(unit === 'session' ? 1 : 0)
    useEffect(() => {
        tabProgress.value = withTiming(unit === 'session' ? 1 : 0, { duration: 220 })
    }, [unit, tabProgress])
    useLayoutEffect(() => {
        perfMark('tabCommitted', Date.now(), { unit })
    }, [unit])
    // In a measuring build, every UI-thread frame over 24 ms is a mark with its length.
    useFrameCallback((frame) => {
        if ((frame.timeSincePreviousFrame ?? 0) > 24) {
            scheduleOnRN(perfMark, 'uiLongFrame', Date.now(), { ms: frame.timeSincePreviousFrame ?? 0 })
        }
    }, FEED_PERF)

    const isReady = useCallback(
        (item: FeedItem): boolean =>
            webPlayer
                ? !item.recording.ongoing
                : hasReadyVideo(item.exports) || readyJobFor(jobs, item.recording.sessionId) !== null,
        [jobs, webPlayer]
    )
    const advanceTarget = useCallback(
        (index: number): number | null => (cards ? nextCardIndex(cards, index, isReady, READY_LOOKAHEAD) : null),
        [cards, isReady]
    )
    const onAdvance = useCallback(
        (index: number): void => {
            const target = advanceTarget(index)
            const from = cards?.[index]
            if (target === null || !cards || !from) {
                return
            }
            const sameRecording = (cards[target] as FeedCardEntry).item === from.item
            trackFeedAutoAdvanced({
                sessionId: from.item.recording.sessionId,
                to: sameRecording ? 'moment' : 'session',
                skipped: cards.slice(index + 1, target).filter((card) => card.first).length,
            })
            scrollTo(target)
        },
        [advanceTarget, cards, scrollTo]
    )

    // A start time for the card a tab switch or Info landed on. It lasts until another card is on screen.
    const [startRequest, setStartRequest] = useState<StartRequest | null>(null)
    const requestId = useRef(0)
    const requestStart = useCallback((key: string, seconds: number): void => {
        requestId.current += 1
        setStartRequest({ key, seconds, id: requestId.current })
    }, [])
    useEffect(() => {
        if (startRequest && currentKey !== null && currentKey !== startRequest.key) {
            setStartRequest(null)
        }
    }, [currentKey, startRequest])

    /**
     * Moment to Full recording keeps the time. Full recording to Moment goes to the moment nearest the time, and keeps
     * the time when it falls inside that moment. The card on screen stays the same card, so its page stays loaded.
     */
    /**
     * Moment to Full recording keeps the time. Full recording to Moment goes to the moment nearest the time, and keeps
     * the time when it falls inside that moment. The card on screen stays the same card, so its page stays loaded.
     * The card answers in the switch's first frame (range, player window); the list renders the new mode once the
     * animations have ended.
     */
    const pendingSwitch = useRef<{ next: FeedUnit; timer: ReturnType<typeof setTimeout> } | null>(null)
    useEffect(() => () => clearTimeout(pendingSwitch.current?.timer), [])
    const switchUnit = (
        next: FeedUnit,
        via: 'tab' | 'swipe' | 'info',
        at?: number,
        preset?: { ordinal: number }
    ): void => {
        const pending = pendingSwitch.current
        if (pending || next === unit) {
            const settled = pending?.next ?? unit
            tabProgress.value = withTiming(settled === 'session' ? 1 : 0, { duration: 160 })
            return
        }
        trackFeedUnitChanged({ unit: next, via })
        const card = currentCard
        let ordinal = card?.ordinal ?? 0
        if (card && at !== undefined) {
            requestStart(card.key, at)
        } else if (card) {
            haptic('selection')
            tabProgress.value = withTiming(next === 'session' ? 1 : 0, { duration: 220 })
            ordinal = handles.current.get(card.key)?.beginSwitch(next, preset).ordinal ?? ordinal
        }
        const commit = (): void => {
            pendingSwitch.current = null
            if (card) {
                const { sessionId } = card.item.recording
                keyOverrides.current = new Map(keyOverrides.current).set(sessionId, { ordinal, key: card.key })
            }
            perfMark('switchCommit', Date.now(), { unit: next })
            set({ unit: next })
        }
        if (via === 'info') {
            commit()
            return
        }
        pendingSwitch.current = { next, timer: setTimeout(commit, SWITCH_COMMIT_MS) }
    }
    const switchRef = useRef(switchUnit)
    switchRef.current = switchUnit
    const swipeUnit = useCallback(
        (next: FeedUnit, preset?: { ordinal: number }): void => switchRef.current(next, 'swipe', undefined, preset),
        []
    )

    // The Sessions page is the page to the right of Full recording: 0 hidden, 1 shown. The swipe and the button both
    // slide it in from the right. It mounts on the first peek and stays mounted, so a later swipe shows it at once.
    const sessionsProgress = useSharedValue(0)
    const [sessionsMounted, setSessionsMounted] = useState(false)
    const [sessionsOpen, setSessionsOpen] = useState(false)
    const suspendedKey = useRef<string | null>(null)
    const currentCardRef = useRef(currentCard)
    currentCardRef.current = currentCard
    const openSessions = (via: 'swipe' | 'button' | 'peek'): void => {
        setSessionsMounted(true)
        if (via === 'peek') {
            return
        }
        trackFeedSourcesOpened({ source, via })
        setSessionsOpen(true)
        sessionsProgress.value = withTiming(1, { duration: SESSIONS_SLIDE_MS })
        const card = currentCardRef.current
        if (card && suspendedKey.current === null) {
            handles.current.get(card.key)?.suspend(true)
            suspendedKey.current = card.key
        }
    }
    const openSessionsRef = useRef(openSessions)
    openSessionsRef.current = openSessions
    const onOpenSessions = useCallback((via: 'swipe' | 'button' | 'peek'): void => openSessionsRef.current(via), [])
    /** `resume` plays the card again unless it was paused before; a pick on the page moves to another card instead. */
    const closeSessions = useCallback(
        (resume: boolean): void => {
            setSessionsOpen(false)
            sessionsProgress.value = withTiming(0, { duration: SESSIONS_SLIDE_MS })
            const key = suspendedKey.current
            suspendedKey.current = null
            if (key && resume) {
                handles.current.get(key)?.suspend(false)
            }
        },
        [sessionsProgress]
    )

    useEffect(() => {
        if (FEED_DEBUG) {
            ;(
                globalThis as {
                    __replayFeed?: {
                        scrollTo: (index: number) => void
                        jump: (index: number) => void
                        current: number
                        cards: () => { key: string; sessionId: string; ordinal: number }[]
                        card: () => FeedCardHandle | null
                    }
                }
            ).__replayFeed = {
                scrollTo,
                jump: (index: number) => {
                    const target = cardsRef.current?.[index]
                    if (target) {
                        setCurrentKey(target.key)
                    }
                },
                current: currentIndex,
                cards: () =>
                    (cardsRef.current ?? []).map((card) => ({
                        key: card.key,
                        sessionId: card.item.recording.sessionId,
                        ordinal: card.ordinal,
                    })),
                card: () => (currentCard ? (handles.current.get(currentCard.key) ?? null) : null),
            }
        }
    }, [scrollTo, currentIndex, currentCard])

    // A recording picked in Sources plays first: the feed moves to it once its page has loaded.
    const [startWith, setStartWith] = useState<string | null>(null)
    useEffect(() => {
        if (!startWith || !cards) {
            return
        }
        const target = cards.find((card) => card.first && card.item.recording.sessionId === startWith)
        setStartWith(null)
        if (target) {
            setCurrentKey(target.key)
        }
    }, [startWith, cards])
    const [settingsOpen, setSettingsOpen] = useState(false)
    const [share, setShare] = useState<{ item: FeedItem; seconds: number } | null>(null)
    const [info, setInfo] = useState<{ item: FeedItem; timeline: FeedTimeline | null; seconds: number } | null>(null)

    const changeSource = (next: FeedSource): void => {
        if (next === source) {
            return
        }
        trackFeedSourceChanged(next)
        set({ source: next })
        setSources(new Map())
        setCurrentKey(null)
        setStartRequest(null)
        lastIndex.current = 0
    }
    const openSpeed = useCallback(() => setSettingsOpen(true), [])
    const openShare = useCallback((item: FeedItem, seconds: number) => setShare({ item, seconds }), [])
    const changeSettings = (patch: Partial<FeedSettings>): void => {
        if (patch.speed !== undefined && unlockFeed()) {
            trackFeedSpeedUnlocked('settings')
        }
        set(patch)
    }
    const shownSettings = useMemo(
        (): FeedSettings => (lock ? { ...settings, speed: lock.rate } : settings),
        [settings, lock]
    )
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
    const [copied, setCopied] = useState<{ id: number; text: string } | null>(null)
    const copyLink = async (item: FeedItem, seconds: number): Promise<void> => {
        const url = webUrlFor(item, seconds)
        if (!url) {
            return
        }
        trackFeedShared({ sessionId: item.recording.sessionId, action: 'copy_link' })
        const done = await Clipboard.setStringAsync(url).catch(() => false)
        setCopied((previous) => ({
            id: (previous?.id ?? 0) + 1,
            text: done ? `Link copied at ${formatOffset(seconds * 1000)}` : "Couldn't copy the link. Try again.",
        }))
    }
    useEffect(() => {
        if (!copied) {
            return undefined
        }
        const timer = setTimeout(() => setCopied(null), 1800)
        return () => clearTimeout(timer)
    }, [copied])
    const openInfo = useCallback((item: FeedItem, timeline: FeedTimeline | null, seconds: number): void => {
        trackFeedInfoOpened(item.recording.sessionId)
        setInfo({ item, timeline, seconds })
    }, [])
    /** An Info event inside a moment plays that moment's card. One outside every moment switches to Full recording. */
    const seekFromInfo = (seconds: number): void => {
        const card = currentCard
        if (!card || !cards) {
            return
        }
        const handle = handles.current.get(card.key)
        if (unit === 'session') {
            handle?.seekToSession(seconds)
            return
        }
        const inside = card.moments.findIndex(
            (moment) => seconds >= moment.startSeconds && seconds <= moment.endSeconds
        )
        if (inside === card.ordinal) {
            handle?.seekToSession(seconds)
            return
        }
        const target = cards.find((entry) => entry.item === card.item && entry.ordinal === inside)
        if (target) {
            requestStart(target.key, seconds)
            scrollTo(target.index)
            return
        }
        switchUnit('session', 'info', seconds)
    }

    const { refresh } = feed
    const recheck = useCallback((): void => void refresh(), [refresh])
    const renderCard = (entry: FeedCardEntry): ReactElement => {
        const target = advanceTarget(entry.index)
        const following = target === null ? null : (cards?.[target] ?? null)
        let next: UpNextInfo | null = null
        if (following) {
            const sameRecording = following.item === entry.item
            const moment = following.moments[following.ordinal]
            next =
                sameRecording && moment
                    ? {
                          title: `${moment.label} · ${formatOffset(moment.anchorSeconds * 1000)}`,
                          person: following.item.recording.personLabel,
                          durationSeconds: moment.endSeconds - moment.startSeconds,
                          sameRecording: true,
                      }
                    : {
                          title: itemTitle(following.item),
                          person: following.item.recording.personLabel,
                          durationSeconds: following.item.recording.durationSeconds,
                          sameRecording: false,
                      }
        }
        let nextReady: { index: number; title: string } | null = null
        for (let position = entry.index + 1; cards && position < cards.length; position += 1) {
            const candidate = cards[position] as FeedCardEntry
            if (candidate.first && !candidate.item.recording.ongoing && isReady(candidate.item)) {
                nextReady = { index: position, title: itemTitle(candidate.item) }
                break
            }
        }
        return (
            <FeedCard
                entry={entry}
                width={size?.width ?? 0}
                height={size?.height ?? 0}
                insets={insets}
                active={focused && entry.index === currentIndex}
                near={Math.abs(entry.index - currentIndex) <= 2}
                pool={(webPlayer ? webPool.get(entry.key) : videoPool.get(entry.index)) ?? null}
                webPlayer={webPlayer}
                demo={demo}
                unit={unit}
                source={source}
                settings={settings}
                startAt={startRequest?.key === entry.key ? startRequest : null}
                next={next}
                nextReady={nextReady}
                tabProgress={tabProgress}
                scrollFade={scrollFade}
                sessionsProgress={sessionsProgress}
                onSwipeUnit={swipeUnit}
                onOpenSessions={onOpenSessions}
                onSource={onSource}
                onAdvance={onAdvance}
                onJumpTo={scrollTo}
                onSpeed={openSpeed}
                onShare={openShare}
                onChat={openChat}
                onInfo={openInfo}
                onOpenWeb={openWeb}
                onRecheck={recheck}
                registerHandle={registerHandle}
            />
        )
    }
    // A recording can have dozens of moments. Only the cards near the current one mount; the row keeps its full height.
    const renderRow = (row: FeedRow): ReactElement => {
        const pageHeight = size?.height ?? 0
        const first = row.cards[0]?.index ?? 0
        return (
            <View
                key={row.item.recording.sessionId}
                style={{ width: size?.width ?? 0, height: row.cards.length * pageHeight }}
            >
                {row.cards.map((entry) =>
                    Math.abs(entry.index - currentIndex) <= MOUNTED_CARDS ? (
                        <View key={entry.key} style={[styles.cardSlot, { top: (entry.index - first) * pageHeight }]}>
                            {renderCard(entry)}
                        </View>
                    ) : null
                )}
            </View>
        )
    }

    let body: ReactElement
    if (access.state !== 'ok') {
        body = (
            <View style={styles.reauth}>
                <ViewsReauthState access={access} feature="replay" />
            </View>
        )
    } else if (feed.error && !items) {
        body = (
            <FeedState
                title="Couldn't load your recordings"
                message="Check your connection and try again."
                actionLabel="Try again"
                onAction={feed.retry}
            />
        )
    } else if (!rows || !size) {
        body = <FeedSkeleton />
    } else if (rows.length === 0) {
        body = (
            <FeedState
                title={feed.pageError ? "Couldn't load more recordings" : emptyTitle(source)}
                message={
                    feed.pageError ? 'Check your connection and try again.' : emptyMessage(source, feed.stillRecording)
                }
                actionLabel={feed.pageError ? 'Try again' : source === 'newest' ? 'Refresh' : 'Show newest'}
                onAction={
                    feed.pageError
                        ? feed.retryMore
                        : source === 'newest'
                          ? () => void feed.refresh()
                          : () => changeSource('newest')
                }
            />
        )
    } else {
        body = (
            <Animated.ScrollView
                ref={setListRef}
                pagingEnabled
                scrollEnabled={!holding}
                // A tap on the status bar would jump back to the first card mid-watch.
                scrollsToTop={false}
                decelerationRate="fast"
                showsVerticalScrollIndicator={false}
                onScroll={onScroll}
                scrollEventThrottle={16}
                onScrollBeginDrag={() => {
                    dragging.current = true
                }}
                onScrollEndDrag={onDragEnd}
                onMomentumScrollEnd={onSettle}
                refreshControl={
                    <RefreshControl
                        refreshing={feed.refreshing}
                        onRefresh={() => void feed.refresh()}
                        tintColor={feedColors.text}
                    />
                }
                testID="feed-list"
            >
                {rows.map(renderRow)}
            </Animated.ScrollView>
        )
    }

    return (
        <View style={styles.screen} onLayout={onLayout}>
            {/* iOS 26 pops a screen on a swipe to the right anywhere in it. The feed's sideways swipes switch tabs and
                pages, so only the edge swipe goes back; over a panel such as Up next, a swipe would leave the feed. */}
            <Stack.Screen options={{ fullScreenGestureEnabled: false }} />
            <StatusBar style={sessionsOpen ? 'dark' : 'light'} />
            {body}
            {feed.pageError && rows && rows.length > 0 && currentIndex >= (cards?.length ?? 0) - LOAD_AHEAD ? (
                <View style={[styles.pageError, { top: insets.top + 56 }]}>
                    <Text style={styles.chipText}>Couldn't load more recordings.</Text>
                    <Pressable44 onPress={feed.retryMore} style={styles.pageRetry} testID="feed-retry-more">
                        <Text style={styles.chipText}>Try again</Text>
                    </Pressable44>
                </View>
            ) : null}
            <Animated.View
                style={[styles.chrome, { top: insets.top + 4 }, chromeStyle]}
                pointerEvents={holding ? 'none' : 'box-none'}
            >
                <Pressable44
                    onPress={back}
                    accessibilityLabel="Back"
                    style={styles.iconButton}
                    pressedStyle={styles.pressed}
                    testID="feed-back"
                >
                    <ChevronLeftIcon size={22} color={feedColors.text} />
                </Pressable44>
                <FeedTabs unit={unit} progress={tabProgress} onSelect={(next) => switchUnit(next, 'tab')} />
                <Pressable44
                    onPress={() => openSessions('button')}
                    accessibilityLabel="Sources"
                    style={styles.iconButton}
                    pressedStyle={styles.pressed}
                    testID="feed-sources"
                >
                    <DashboardIcon size={19} color={feedColors.text} />
                </Pressable44>
            </Animated.View>
            <HoldHud top={insets.top + 8} />
            {copied ? (
                <View style={[styles.copied, { top: insets.top + 60 }]} pointerEvents="none" testID="feed-copied">
                    <Text style={styles.chipText}>{copied.text}</Text>
                </View>
            ) : null}
            <FeedSourcesPage
                progress={sessionsProgress}
                mounted={sessionsMounted}
                open={sessionsOpen}
                width={size?.width ?? 0}
                playing={source}
                playingSession={currentCard?.item.recording.sessionId ?? null}
                onPlay={(next, sessionId) => {
                    if (sessionId !== null && hidden.includes(sessionId)) {
                        closeSessions(true)
                        return
                    }
                    if (next !== source) {
                        closeSessions(false)
                        changeSource(next)
                        setStartWith(sessionId)
                        return
                    }
                    const target =
                        sessionId === null
                            ? cards?.[0]
                            : cards?.find((card) => card.first && card.item.recording.sessionId === sessionId)
                    if (!target) {
                        closeSessions(true)
                        return
                    }
                    const handle = handles.current.get(target.key)
                    if (target.key === currentCard?.key) {
                        closeSessions(!handle)
                        handle?.playSelection(sessionId === null)
                    } else {
                        closeSessions(false)
                        setCurrentKey(target.key)
                    }
                }}
                onClose={() => closeSessions(true)}
            />
            <FeedSettingsSheet
                visible={settingsOpen}
                settings={shownSettings}
                locked={lock !== null}
                onChange={changeSettings}
                onClose={() => setSettingsOpen(false)}
            />
            <FeedShareSheet
                visible={share !== null}
                seconds={share?.seconds ?? 0}
                onCopyLink={() => {
                    if (share) {
                        void copyLink(share.item, share.seconds)
                    }
                    setShare(null)
                }}
                onOpenWeb={
                    share && webUrlFor(share.item, share.seconds)
                        ? () => {
                              trackFeedShared({ sessionId: share.item.recording.sessionId, action: 'open_web' })
                              openWeb(share.item, share.seconds)
                              setShare(null)
                          }
                        : null
                }
                onClose={() => setShare(null)}
            />
            <FeedInfoSheet
                visible={info !== null}
                item={info?.item ?? null}
                timeline={info?.timeline ?? null}
                nowSeconds={info?.seconds ?? 0}
                onSeek={seekFromInfo}
                onOpenWeb={info && webUrlFor(info.item, 0) ? () => openWeb(info.item, 0) : null}
                onNotInterested={() => {
                    if (info) {
                        trackFeedNotInterested(info.item.recording.sessionId)
                        hide(info.item.recording.sessionId)
                    }
                    setInfo(null)
                }}
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
    pageError: {
        position: 'absolute',
        alignSelf: 'center',
        backgroundColor: feedColors.glassStrong,
        paddingStart: 12,
        borderRadius: 16,
        flexDirection: 'row',
        alignItems: 'center',
    },
    pageRetry: { paddingHorizontal: 12 },
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
    cardSlot: {
        position: 'absolute',
        left: 0,
        right: 0,
    },
    iconButton: {
        ...glassPill,
        width: 44,
        justifyContent: 'center',
    },
    copied: {
        ...glassPill,
        position: 'absolute',
        alignSelf: 'center',
        height: 36,
        paddingHorizontal: 16,
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
