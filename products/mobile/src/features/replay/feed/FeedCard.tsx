import { VideoView } from 'expo-video'
import { memo, type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, {
    Easing,
    FadeIn,
    FadeOut,
    type SharedValue,
    useAnimatedStyle,
    useSharedValue,
    withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { pickReusableExport } from '@/api/replayVideo'
import { formatRelativeAgo } from '@/lib/dates'
import { haptic } from '@/lib/haptics'
import { FadeEdge } from '@/ui/FadeEdge'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { createStyles } from '@/ui/theme'

import { useFrameUrl } from '../hooks'
import type { SessionSummary } from '../replayModel'
import { countryFlag, formatOffset } from '../sessionAdapters'
import { sessionSecondsForVideoSeconds, videoSecondsForSessionSeconds } from '../video/videoTime'
import { ReplayWebView } from '../web/ReplayWebView'
import { FeedRail } from './FeedRail'
import { FeedScrubber } from './FeedScrubber'
import { itemTitle, type RenderSpec, renderKey, renderViewport, sessionStartSeconds } from './feedAdapters'
import {
    trackFeedEventJump,
    trackFeedHoldStarted,
    trackFeedItemShown,
    trackFeedLoadFailed,
    trackFeedSpeedLocked,
    trackFeedSpeedUnlocked,
} from './feedAnalytics'
import { type FeedCardEntry, nearestMoment } from './feedCards'
import { armHold, beginHold, finishHold, holdHaptic, holdPull, useFeedHold } from './feedHoldStore'
import {
    type FeedEvent,
    type FeedItem,
    type FeedSettings,
    type FeedSource,
    type FeedTimeline,
    type FeedUnit,
    MOMENT_WINDOW,
    type Moment,
} from './feedModel'
import { SESSIONS_SLIDE_MS, swipeDrag, swipeOutcome } from './feedPages'
import { perfMark } from './feedPerf'
import type { FeedPlayer, PoolPlayer } from './feedPlayer'
import { feedColors, feedTextShadow, type TickKind, tickColors } from './feedStyle'
import { HOLD_PULL, playbackRate } from './holdLock'
import { type LadderState, RenderLadder } from './RenderLadder'
import { startRender, useRenderQueue } from './renderQueue'
import { clusterTicks, type ScrubberTick } from './scrubberMarks'
import { UpNextCard } from './UpNextCard'
import { useFeedTimeline } from './useFeed'
import type { PoolSource } from './usePlayerPool'

/** A card renders only after this long on screen, or on a tap of Play, so a swipe past never spends the video cap. */
export const DWELL_MS = 1500
const JUMP_SECONDS = 10
const RANGE_MS = 260

export interface FeedCardHandle {
    /** Seeks inside the card's own window and plays. */
    seekToSession: (seconds: number) => void
    currentSeconds: () => number
    /**
     * The first frame of a tab switch on this card: the range animates, and when the time stays the player only moves
     * its end. `preset` is the moment a swipe already chose and animated to on the UI thread.
     */
    beginSwitch: (next: FeedUnit, preset?: { ordinal: number }) => SwitchPlan
    /** Pauses while the Sessions page covers the card, and plays again after, unless it was paused before. */
    suspend: (on: boolean) => void
    playSelection: (restart: boolean) => void
    hold: (on: boolean) => void
    togglePause: () => void
}

/** What plays after this card: the next moment of the same recording, or another recording. */
export interface UpNextInfo {
    title: string
    person: string
    durationSeconds: number
    sameRecording: boolean
}

export interface SwitchPlan {
    /** The moment the card plays after the switch; on Full recording, the moment it played before. */
    ordinal: number
    /** False when the time falls outside that moment, so the card seeks to the moment's start. */
    keepTime: boolean
}

/** A start time a tab switch or Info asked for. A new `id` restarts the card there. */
export interface StartRequest {
    key: string
    seconds: number
    id: number
}

interface FeedCardProps {
    entry: FeedCardEntry
    width: number
    height: number
    insets: { top: number; bottom: number }
    active: boolean
    near: boolean
    pool: PoolPlayer | null
    /** Plays the recording's snapshots in a WebView: no render, no export. */
    webPlayer: boolean
    demo: boolean
    unit: FeedUnit
    source: FeedSource
    settings: FeedSettings
    startAt: StartRequest | null
    next: UpNextInfo | null
    nextReady: { index: number; title: string } | null
    /** 0 on Moment, 1 on Full recording. A sideways swipe moves it with the finger. */
    tabProgress: SharedValue<number>
    /** 1 when a page is settled, down to 0.5 while the feed is dragged between pages. */
    scrollFade: SharedValue<number>
    /** 0 hidden, 1 shown. A swipe to the left on Full recording drags the Sessions page in. */
    sessionsProgress: SharedValue<number>
    onSwipeUnit: (unit: FeedUnit, preset?: { ordinal: number }) => void
    /** `peek` mounts the page as a drag starts to show it; `swipe` opens it. */
    onOpenSessions: (via: 'swipe' | 'button' | 'peek') => void
    onSource: (index: number, source: PoolSource | null) => void
    onAdvance: (index: number) => void
    onJumpTo: (index: number) => void
    onSpeed: () => void
    onShare: (item: FeedItem, seconds: number) => void
    onChat: (item: FeedItem) => void
    onInfo: (item: FeedItem, timeline: FeedTimeline | null, seconds: number) => void
    onOpenWeb: (item: FeedItem, seconds: number) => void
    onRecheck: () => void
    registerHandle: (key: string, handle: FeedCardHandle | null) => void
}

function tickKind(event: FeedEvent): TickKind | null {
    switch (event.kind) {
        case 'rageclick':
        case 'deadclick':
            return 'rage'
        case 'exception':
            return 'error'
        case 'custom':
            return 'custom'
        default:
            return null
    }
}

function posterChapter(summary: SessionSummary | null, seconds: number): number | null {
    const ms = seconds * 1000
    const chapter =
        summary?.chapters.find(
            (item) => item.hasFrame && item.startMs <= ms && (item.endMs === null || ms < item.endMs)
        ) ?? summary?.chapters.find((item) => item.hasFrame && item.isKeyMoment)
    return chapter ? chapter.index : null
}

function signed(seconds: number): string {
    const sign = seconds < 0 ? '-' : '+'
    return `${sign}${formatOffset(Math.abs(seconds) * 1000)}`
}

function FeedCardBody({
    entry,
    width,
    height,
    insets,
    active,
    near,
    pool,
    webPlayer,
    demo,
    unit,
    source,
    settings,
    startAt,
    next,
    nextReady,
    tabProgress,
    scrollFade,
    sessionsProgress,
    onSwipeUnit,
    onOpenSessions,
    onSource,
    onAdvance,
    onJumpTo,
    onSpeed,
    onShare,
    onChat,
    onInfo,
    onOpenWeb,
    onRecheck,
    registerHandle,
}: FeedCardProps): ReactElement {
    const styles = useStyles()
    const { item, index, moments, key: cardKey } = entry
    const { recording, summary } = item
    const { sessionId, durationSeconds } = recording
    const timeline = useFeedTimeline(item, near)
    const moment = moments[Math.min(entry.ordinal, moments.length - 1)] as Moment
    const domain =
        unit === 'moment' ? { start: moment.startSeconds, end: moment.endSeconds } : { start: 0, end: durationSeconds }
    const startSeconds =
        startAt?.seconds ??
        (unit === 'moment' ? moment.startSeconds : sessionStartSeconds(moments, summary, MOMENT_WINDOW))

    // Each card listens to its own two jobs only, so one render's progress does not re-render every card.
    const renderScope = useRenderQueue((state) => state.scope)
    const fullJob = useRenderQueue((state) => state.jobs[`${sessionId}:full`])
    const limitMessage = useRenderQueue((state) => state.limitMessage)
    const fullKnown = useMemo(
        () => pickReusableExport(item.exports, durationSeconds)?.has_content === true,
        [item.exports, durationSeconds]
    )
    const useFull = unit === 'session' || fullKnown || fullJob?.state.status === 'ready'
    const spec: RenderSpec = useFull
        ? { kind: 'full', sessionId, durationSeconds }
        : {
              kind: 'clip',
              sessionId,
              durationSeconds,
              startSeconds: moment.startSeconds,
              endSeconds: moment.endSeconds,
          }
    const key = renderKey(spec)
    const job = useRenderQueue((state) => state.jobs[key]) ?? null
    const viewport = renderViewport(timeline?.viewport ?? null)
    const specRef = useRef(spec)
    specRef.current = spec
    const viewportRef = useRef(viewport)
    viewportRef.current = viewport

    // Attaching a video that exists or is rendering costs nothing, so neighbours do it before they are on screen.
    // biome-ignore lint/correctness/useExhaustiveDependencies: `key` names the spec, which the ref holds.
    useEffect(() => {
        if (near && !recording.ongoing && !webPlayer) {
            startRender({
                spec: specRef.current,
                scope: renderScope,
                known: item.exports,
                allowCreate: false,
                trigger: 'reuse',
                viewport: viewportRef.current,
            })
        }
    }, [near, key, recording.ongoing, item.exports, webPlayer, renderScope])

    const canRender = !recording.ongoing && limitMessage === null && (spec.kind === 'full' || timeline !== null)
    const requestRender = useCallback(
        (trigger: 'dwell' | 'tap', reloadSource = false): void => {
            if (!webPlayer) {
                startRender({
                    spec: specRef.current,
                    scope: renderScope,
                    known: null,
                    allowCreate: !reloadSource,
                    reloadSource,
                    trigger,
                    viewport: viewportRef.current,
                })
            }
        },
        [webPlayer, renderScope]
    )
    useEffect(() => {
        if (webPlayer || !active || job !== null || !canRender) {
            return undefined
        }
        const timer = setTimeout(() => requestRender('dwell'), DWELL_MS)
        return () => clearTimeout(timer)
    }, [webPlayer, active, job, canRender, requestRender])

    const ready = job?.state.status === 'ready' ? job.state : null
    const sourceKey = webPlayer ? `web:${cardKey}` : ready ? `${key}#${ready.exportId}` : null
    const videoSource = ready?.source
    useEffect(() => {
        if (!webPlayer) {
            onSource(index, videoSource && sourceKey ? { key: sourceKey, source: videoSource } : null)
        }
    }, [index, sourceKey, videoSource, onSource, webPlayer])
    useEffect(() => () => onSource(index, null), [index, onSource])

    const matchingVideo = pool?.kind === 'video' && pool.key === sourceKey && pool.source === videoSource
    const videoLoadFailed = matchingVideo && pool.failed
    const loaded = pool !== null && pool.key === sourceKey && pool.loaded && (pool.kind === 'web' || matchingVideo)
    const player: FeedPlayer | null = loaded ? pool.player : null
    const video = loaded && pool.kind === 'video' ? pool.player : null
    const web = loaded && pool.kind === 'web' ? pool.player : null
    const [webError, setWebError] = useState<string | null>(null)
    const context = ready?.context
    const contextRef = useRef(context)
    contextRef.current = context

    const aspect =
        context?.width && context.height
            ? context.width / context.height
            : timeline?.viewport
              ? timeline.viewport.width / timeline.viewport.height
              : 1.6
    const portrait = aspect < 1
    // A phone recording sits between the top chrome and the caption, so nothing covers its own header and tab bar.
    // A desktop page is letterboxed a little above the middle.
    const framed = portrait
    const frame = (() => {
        if (framed) {
            const top = insets.top + 54
            const frameHeight = Math.max(200, height - top - (Math.max(insets.bottom - 8, 10) + 52) - 132)
            const frameWidth = Math.min(width - 32, frameHeight * aspect)
            return { top, height: frameWidth / aspect, left: (width - frameWidth) / 2, width: frameWidth }
        }
        const frameHeight = width / aspect
        return {
            top: Math.max(insets.top + 96, (height - frameHeight) / 2 - height * 0.1),
            height: frameHeight,
            left: 0,
            width,
        }
    })()

    const position = useSharedValue(startSeconds)
    const [paused, setPaused] = useState(false)
    const pausedRef = useRef(false)
    pausedRef.current = paused
    const [ended, setEnded] = useState(false)
    const endedRef = useRef(false)
    endedRef.current = ended
    const [countdownCancelled, setCountdownCancelled] = useState(false)
    const holdNow = useFeedHold((state) => (active ? state.hold : null))
    const lock = useFeedHold((state) => state.lock)
    const holding = holdNow !== null
    const [firstFrame, setFirstFrame] = useState(false)
    const pendingSeek = useRef<number | null>(null)
    const scrubbing = useRef<{ wasPlaying: boolean; startSeconds: number } | null>(null)
    const domainRef = useRef(domain)
    domainRef.current = domain
    const unitRef = useRef(unit)
    unitRef.current = unit
    // The bar's range lives here, so a tab swipe animates it on the UI thread before the card renders in its new mode.
    const rangeStart = useSharedValue(domain.start)
    const rangeEnd = useSharedValue(domain.end)
    const rangeTarget = useRef({ start: domain.start, end: domain.end })
    const marksShown = useSharedValue(1)
    // Set from a tab switch's first frame until the card renders in the new mode. 'keep' means playback goes on from
    // the same time, so the new mode's start must not prepare or seek the player again.
    const switching = useRef<'keep' | 'seek' | null>(null)
    useEffect(() => {
        const target = rangeTarget.current
        if (target.start === domain.start && target.end === domain.end) {
            return
        }
        rangeTarget.current = { start: domain.start, end: domain.end }
        rangeStart.value = active ? withTiming(domain.start, { duration: RANGE_MS }) : domain.start
        rangeEnd.value = active ? withTiming(domain.end, { duration: RANGE_MS }) : domain.end
    }, [domain.start, domain.end, active, rangeStart, rangeEnd])

    // biome-ignore lint/correctness/useExhaustiveDependencies: a new video means a new first frame.
    useEffect(() => {
        setFirstFrame(false)
    }, [sourceKey])

    const seekSession = useCallback(
        (seconds: number): void => {
            position.value = seconds
            if (!player) {
                return
            }
            const videoSeconds = videoSecondsForSessionSeconds(seconds, contextRef.current)
            if (player.status === 'readyToPlay') {
                player.currentTime = videoSeconds
                pendingSeek.current = null
            } else {
                pendingSeek.current = videoSeconds
            }
        },
        [player, position]
    )

    const currentRate = useCallback((): number => {
        const state = useFeedHold.getState()
        return playbackRate(settings.speed, active ? state.hold : null, state.lock)
    }, [settings.speed, active])
    const play = useCallback((): void => {
        if (!player) {
            return
        }
        player.playbackRate = currentRate()
        player.play()
    }, [player, currentRate])

    const startKey = `${unit}:${moment.key}:${startSeconds}:${startAt?.id ?? ''}`
    // A WebView player loads only the blocks it needs, so it learns the window before the first seek reaches it.
    // biome-ignore lint/correctness/useExhaustiveDependencies: `startKey` names the window; the rest are read through refs.
    useEffect(() => {
        if (switching.current !== 'keep') {
            web?.prepare(startSeconds, unit === 'moment' ? domain.end : null, active && !pausedRef.current)
        }
    }, [web, startKey])
    useEffect(() => {
        if (!web) {
            return undefined
        }
        const updateError = (): void =>
            setWebError(web.status === 'error' ? (web.errorMessage ?? "Couldn't play this recording.") : null)
        updateError()
        const frame = web.onFirstFrame(() => setFirstFrame(true))
        const status = web.addListener('statusChange', updateError)
        return () => {
            frame.remove()
            status.remove()
        }
    }, [web])
    // biome-ignore lint/correctness/useExhaustiveDependencies: `startKey` names the start; the rest are read through refs.
    useEffect(() => {
        if (!player || (active && switching.current === 'keep')) {
            return
        }
        if (!active) {
            player.pause()
            seekSession(startSeconds)
            setEnded(false)
            setPaused(false)
            setCountdownCancelled(false)
            return
        }
        seekSession(startSeconds)
        setEnded(false)
        if (!pausedRef.current) {
            play()
        }
    }, [active, player, startKey])

    useEffect(() => {
        if (player && active) {
            player.playbackRate = playbackRate(settings.speed, holdNow, lock)
        }
    }, [player, active, holdNow, lock, settings.speed])
    useEffect(() => {
        web?.setSkipInactivity(settings.skipInactivity)
    }, [web, settings.skipInactivity])
    // The switch is over once the card has rendered in its new mode; this runs after the two effects above.
    // biome-ignore lint/correctness/useExhaustiveDependencies: `startKey` names the mode and start the switch ends in.
    useEffect(() => {
        switching.current = null
    }, [startKey])

    // Gestures and the end-of-window timer reach the newest handlers through this ref.
    const handlers = useRef<{
        togglePause: () => void
        jump: (direction: 1 | -1) => void
        holdStart: () => void
        holdEnd: (cancelled: boolean) => void
    } | null>(null)

    // With Autoplay next on, the next moment of the same recording follows at once. Another recording waits for the
    // Up next card and its countdown, and with Autoplay next off every card stops on Up next.
    const nextMomentRef = useRef(false)
    nextMomentRef.current = next?.sameRecording === true && settings.autoplayNext
    const finishWindow = useCallback((): void => {
        if (endedRef.current || !player || switching.current) {
            return
        }
        player.pause()
        if (nextMomentRef.current) {
            endedRef.current = true
            onAdvance(index)
            return
        }
        endedRef.current = true
        setEnded(true)
        setCountdownCancelled(false)
    }, [player, onAdvance, index])

    useEffect(() => {
        if (!player || !active) {
            return undefined
        }
        const time = player.addListener('timeUpdate', ({ currentTime }) => {
            if (scrubbing.current) {
                return
            }
            const seconds = sessionSecondsForVideoSeconds(currentTime, contextRef.current)
            const jump = Math.abs(seconds - position.value) > 1.5
            position.value = jump ? seconds : withTiming(seconds, { duration: 250, easing: Easing.linear })
            if (player.playing) {
                setFirstFrame(true)
            }
            if (unitRef.current === 'moment' && player.playing && seconds >= domainRef.current.end - 0.15) {
                finishWindow()
            }
        })
        const end = player.addListener('playToEnd', () => finishWindow())
        return () => {
            time.remove()
            end.remove()
        }
    }, [player, active, position, finishWindow])

    // A neighbour seeks to its start while off screen too, so it arrives on the right frame.
    useEffect(() => {
        if (!player) {
            return undefined
        }
        const apply = (): void => {
            if (pendingSeek.current !== null && player.status === 'readyToPlay') {
                player.currentTime = pendingSeek.current
                pendingSeek.current = null
            }
        }
        const status = player.addListener('statusChange', apply)
        const load = player.addListener('sourceLoad', apply)
        apply()
        return () => {
            status.remove()
            load.remove()
        }
    }, [player])

    const togglePause = (): void => {
        if (!player || ended) {
            return
        }
        if (paused) {
            play()
            setPaused(false)
        } else {
            player.pause()
            setPaused(true)
        }
    }

    const [toast, setToast] = useState<{ id: number; text: string } | null>(null)
    const showToast = useCallback((text: string): void => {
        setToast((previous) => ({ id: (previous?.id ?? 0) + 1, text }))
    }, [])
    useEffect(() => {
        if (!toast) {
            return undefined
        }
        const timer = setTimeout(() => setToast(null), 1800)
        return () => clearTimeout(timer)
    }, [toast])

    const jump = (direction: 1 | -1): void => {
        if (!player) {
            return
        }
        const now = position.value
        // A moment is short, so its clicks count as events; a whole session has too many of them.
        const candidates = (timeline?.events ?? []).filter(
            (event) =>
                (unit === 'moment' || event.kind !== 'click') &&
                event.seconds >= domain.start &&
                event.seconds <= domain.end
        )
        const target =
            direction > 0
                ? candidates.find((event) => event.seconds > now + 1.5)
                : [...candidates].reverse().find((event) => event.seconds < now - 2.5)
        haptic('light')
        if (target) {
            seekSession(Math.max(domain.start, target.seconds - 1))
            showToast(`${formatOffset(target.seconds * 1000)} · ${target.label}`)
            trackFeedEventJump({
                sessionId,
                direction: direction > 0 ? 'next' : 'previous',
                kind: target.kind,
                via: 'double_tap',
            })
        } else {
            seekSession(Math.min(domain.end, Math.max(domain.start, now + direction * JUMP_SECONDS)))
            showToast(direction > 0 ? `+${JUMP_SECONDS} s` : `-${JUMP_SECONDS} s`)
            trackFeedEventJump({
                sessionId,
                direction: direction > 0 ? 'next' : 'previous',
                kind: 'seconds',
                via: 'double_tap',
            })
        }
        if (ended) {
            setEnded(false)
            endedRef.current = false
            play()
        }
    }

    const holdStart = (): void => {
        if (!player || ended || !active) {
            return
        }
        const started = beginHold(settings.speed)
        if (!started) {
            return
        }
        holdHaptic('start')
        trackFeedHoldStarted({ sessionId, rate: started.rate, locked: started.locked })
        player.playbackRate = started.rate
        player.play()
    }
    const holdEnd = (cancelled: boolean): void => {
        const result = finishHold(cancelled)
        if (result === 'locked') {
            holdHaptic('locked')
            trackFeedSpeedLocked(useFeedHold.getState().lock?.rate ?? 0)
        } else if (result === 'unlocked') {
            holdHaptic('unlocked')
            trackFeedSpeedUnlocked('pull')
        }
        if (player && pausedRef.current) {
            player.pause()
        }
    }

    const beginSwitch = (next: FeedUnit, preset?: { ordinal: number }): SwitchPlan => {
        const seconds = position.value
        let ordinal = entry.ordinal
        let start = 0
        let end = durationSeconds
        if (next === 'moment') {
            ordinal = preset?.ordinal ?? nearestMoment(moments, seconds)
            const target = moments[ordinal] ?? moment
            start = target.startSeconds
            end = target.endSeconds
        }
        const keepTime = next === 'session' || (seconds >= start && seconds <= end)
        if (!preset) {
            rangeStart.value = withTiming(start, { duration: RANGE_MS })
            rangeEnd.value = withTiming(end, { duration: RANGE_MS })
            marksShown.value = withTiming(0, { duration: 90 })
        }
        perfMark('rangeAnimStart', Date.now(), { start, end })
        rangeTarget.current = { start, end }
        switching.current = keepTime && web ? 'keep' : 'seek'
        if (keepTime && web) {
            web.setWindow(next === 'session' ? null : end)
            if (endedRef.current) {
                endedRef.current = false
                setEnded(false)
                play()
            }
        }
        return { ordinal, keepTime }
    }
    const beginSwitchRef = useRef(beginSwitch)
    beginSwitchRef.current = beginSwitch
    const resumeAfter = useRef(false)
    const suspend = (on: boolean): void => {
        if (on) {
            resumeAfter.current = !pausedRef.current && !endedRef.current
            if (resumeAfter.current) {
                player?.pause()
            }
        } else if (resumeAfter.current) {
            resumeAfter.current = false
            play()
        }
    }
    const suspendRef = useRef(suspend)
    suspendRef.current = suspend

    handlers.current = { togglePause, jump, holdStart, holdEnd }
    const swipeUnitRef = useRef(onSwipeUnit)
    swipeUnitRef.current = onSwipeUnit
    const openSessionsRef = useRef(onOpenSessions)
    openSessionsRef.current = onOpenSessions
    const dispatch = useCallback(
        (
            action: 'toggle' | 'jump' | 'holdStart' | 'holdArm' | 'holdEnd' | 'tab' | 'sessions',
            value: number,
            at?: number,
            ordinal?: number
        ): void => {
            const current = handlers.current
            if (!current) {
                return
            }
            if (action === 'toggle') {
                current.togglePause()
            } else if (action === 'jump') {
                current.jump(value > 0 ? 1 : -1)
            } else if (action === 'holdStart') {
                current.holdStart()
            } else if (action === 'holdArm') {
                armHold(value > 0 ? HOLD_PULL : 0)
            } else if (action === 'holdEnd') {
                current.holdEnd(value > 0)
            } else if (action === 'sessions') {
                openSessionsRef.current(value > 0 ? 'swipe' : 'peek')
            } else {
                perfMark('gestureEnd', at)
                perfMark('switchJs')
                swipeUnitRef.current(
                    value > 0 ? 'session' : 'moment',
                    ordinal === undefined || ordinal < 0 ? undefined : { ordinal }
                )
            }
        },
        []
    )
    const holdArmed = useSharedValue(false)
    const holdActive = useSharedValue(false)
    const peeked = useSharedValue(false)
    const tabBase = unit === 'session' ? 1 : 0
    const gesture = useMemo(() => {
        const half = width / 2
        const singleTap = Gesture.Tap()
            .maxDuration(260)
            .onEnd((_event, success) => {
                'worklet'
                if (success) {
                    scheduleOnRN(dispatch, 'toggle', 0)
                }
            })
        const doubleTap = Gesture.Tap()
            .numberOfTaps(2)
            .maxDelay(240)
            .onEnd((event, success) => {
                'worklet'
                if (success) {
                    scheduleOnRN(dispatch, 'jump', event.x > half ? 1 : -1)
                }
            })
        // A hold owns the finger once it starts, so its pull never pages the feed or switches the tab.
        const hold = Gesture.Pan()
            .activateAfterLongPress(380)
            .onStart(() => {
                'worklet'
                holdActive.value = true
                holdArmed.value = false
                holdPull.value = 0
                scheduleOnRN(dispatch, 'holdStart', 0)
            })
            .onUpdate((event) => {
                'worklet'
                const pull = Math.max(0, event.translationY)
                holdPull.value = pull
                const armed = pull >= HOLD_PULL
                if (armed !== holdArmed.value) {
                    holdArmed.value = armed
                    scheduleOnRN(dispatch, 'holdArm', armed ? 1 : 0)
                }
            })
            .onFinalize((_event, success) => {
                'worklet'
                if (holdActive.value) {
                    holdActive.value = false
                    scheduleOnRN(dispatch, 'holdEnd', success ? 0 : 1)
                }
            })
        // Sideways, the pages run Moment, Full recording, Sessions. On Full recording a swipe to the left brings the
        // Sessions page in from the right. The tab highlight, the bar's range and the page follow the finger on the UI
        // thread, so they never wait for the JS thread.
        const sideways = (): ReturnType<typeof Gesture.Pan> =>
            Gesture.Pan()
                .activeOffsetX([-22, 22])
                .failOffsetY([-14, 14])
                .onBegin(() => {
                    'worklet'
                    peeked.value = false
                })
                .onUpdate((event) => {
                    'worklet'
                    const drag = swipeDrag(tabBase, event.translationX, width)
                    tabProgress.value = drag.tab
                    sessionsProgress.value = drag.sessions
                    if (drag.sessions > 0 && !peeked.value) {
                        peeked.value = true
                        scheduleOnRN(dispatch, 'sessions', 0)
                    }
                })
                .onEnd((event, success) => {
                    'worklet'
                    const outcome = success ? swipeOutcome(tabBase, event.translationX, event.velocityX) : 'stay'
                    if (outcome === 'sessions') {
                        sessionsProgress.value = withTiming(1, { duration: SESSIONS_SLIDE_MS })
                        scheduleOnRN(dispatch, 'sessions', 1)
                        return
                    }
                    sessionsProgress.value = withTiming(0, { duration: 160 })
                    if (outcome === 'stay') {
                        tabProgress.value = withTiming(tabBase, { duration: 160 })
                        return
                    }
                    const target = outcome === 'session' ? 1 : 0
                    let ordinal = -1
                    let start = 0
                    let end = durationSeconds
                    if (outcome === 'moment') {
                        ordinal = nearestMoment(moments, position.value)
                        const chosen = moments[ordinal] ?? moment
                        start = chosen.startSeconds
                        end = chosen.endSeconds
                    }
                    tabProgress.value = withTiming(target, { duration: 180 })
                    rangeStart.value = withTiming(start, { duration: RANGE_MS })
                    rangeEnd.value = withTiming(end, { duration: RANGE_MS })
                    marksShown.value = withTiming(0, { duration: 90 })
                    scheduleOnRN(dispatch, 'tab', target, Date.now(), ordinal)
                })
        // The Up next panel covers the middle of the video, so it gets the same swipe; its buttons still take taps.
        return { video: Gesture.Race(sideways(), Gesture.Exclusive(hold, doubleTap, singleTap)), panel: sideways() }
    }, [
        width,
        tabBase,
        tabProgress,
        sessionsProgress,
        dispatch,
        holdActive,
        holdArmed,
        peeked,
        moments,
        moment,
        durationSeconds,
        position,
        rangeStart,
        rangeEnd,
        marksShown,
    ])

    const seekInWindow = useCallback(
        (seconds: number): void => {
            seekSession(seconds)
            if (endedRef.current) {
                setEnded(false)
                endedRef.current = false
            }
            play()
        },
        [seekSession, play]
    )
    const playSelection = useCallback(
        (restart: boolean): void => {
            resumeAfter.current = false
            pausedRef.current = false
            setPaused(false)
            setCountdownCancelled(false)
            seekInWindow(restart || endedRef.current ? domainRef.current.start : position.value)
        },
        [seekInWindow, position]
    )
    useEffect(() => {
        if (!active) {
            return undefined
        }
        registerHandle(cardKey, {
            seekToSession: seekInWindow,
            currentSeconds: () => position.value,
            beginSwitch: (next, preset) => beginSwitchRef.current(next, preset),
            suspend: (on) => suspendRef.current(on),
            playSelection,
            hold: (on) => (on ? handlers.current?.holdStart() : handlers.current?.holdEnd(false)),
            togglePause: () => handlers.current?.togglePause(),
        })
        return () => registerHandle(cardKey, null)
    }, [active, cardKey, registerHandle, seekInWindow, position, playSelection])

    // biome-ignore lint/correctness/useExhaustiveDependencies: one event per arrival on screen.
    useEffect(() => {
        if (active) {
            trackFeedItemShown({
                sessionId,
                position: index,
                ready: item.readyAtLoad,
                unit,
                source,
                moments: moments.length,
            })
        }
    }, [active])

    let ladder: LadderState | null = null
    if (webPlayer) {
        ladder = null
    } else if (videoLoadFailed) {
        ladder = { kind: 'failed', message: "Couldn't load this video." }
    } else if (recording.ongoing) {
        ladder = { kind: 'recording', shownSeconds: durationSeconds }
    } else if (!loaded || !firstFrame) {
        const state = job?.state
        if (state?.status === 'preparing') {
            ladder = { kind: 'preparing', clip: spec.kind === 'clip', startedAt: state.startedAt }
        } else if (state?.status === 'checking' && job?.created) {
            ladder = { kind: 'preparing', clip: spec.kind === 'clip', startedAt: Date.now() }
        } else if (state?.status === 'error') {
            ladder =
                state.kind === 'limit_reached'
                    ? { kind: 'limit', message: state.message }
                    : { kind: 'failed', message: state.message }
        } else if (!job && limitMessage !== null) {
            ladder = { kind: 'limit', message: limitMessage }
        } else if (!job && active) {
            ladder = { kind: 'waiting' }
        }
    }

    const posterIndex = posterChapter(summary, unit === 'moment' ? moment.anchorSeconds : startSeconds)
    const poster = useFrameUrl(near ? (summary?.observationId ?? null) : null, posterIndex)
    const posterUri = poster.data ?? null
    const showVideo = loaded && firstFrame
    const posterStyle = useAnimatedStyle(
        () => ({ opacity: withTiming(showVideo ? 0 : 1, { duration: 180 }) }),
        [showVideo]
    )

    const ticks = useMemo((): ScrubberTick[] => {
        const fromEvents = (timeline?.events ?? []).flatMap((event): ScrubberTick[] => {
            const kind = tickKind(event)
            return kind && event.seconds >= domain.start && event.seconds <= domain.end
                ? [{ key: event.key, seconds: event.seconds, kind, label: event.label }]
                : []
        })
        const keyMs = summary?.keyMomentMs
        if (typeof keyMs === 'number' && keyMs / 1000 >= domain.start && keyMs / 1000 <= domain.end) {
            fromEvents.push({ key: 'key', seconds: keyMs / 1000, kind: 'key', label: 'Key moment' })
        }
        return clusterTicks(fromEvents, domain.start, domain.end, Math.max(0, width - 32))
    }, [timeline, summary, domain.start, domain.end, width])
    // A switch fades the marks out on its first frame. They come back once they are placed for the new range.
    // biome-ignore lint/correctness/useExhaustiveDependencies: new marks are what bring them back.
    useEffect(() => {
        marksShown.value = withTiming(1, { duration: 160 })
    }, [ticks, marksShown])

    const onScrubStart = useCallback((): void => {
        scrubbing.current = { wasPlaying: player?.playing ?? false, startSeconds: position.value }
        player?.pause()
    }, [player, position])
    const lastScrubSeek = useRef(0)
    const onScrub = useCallback(
        (seconds: number): void => {
            const now = Date.now()
            if (player && now - lastScrubSeek.current > 90) {
                lastScrubSeek.current = now
                player.currentTime = videoSecondsForSessionSeconds(seconds, contextRef.current)
            }
        },
        [player]
    )
    const onScrubEnd = useCallback(
        (seconds: number, tick: ScrubberTick | null): void => {
            const wasPlaying = scrubbing.current?.wasPlaying ?? false
            scrubbing.current = null
            seekSession(seconds)
            if (tick) {
                trackFeedEventJump({ sessionId, direction: 'next', kind: tick.kind, via: 'scrubber' })
            }
            if (wasPlaying && !pausedRef.current) {
                play()
            }
        },
        [seekSession, play, sessionId]
    )

    const cancelScrub = (): void => {
        const previous = scrubbing.current
        setScrubbingUI(false)
        if (previous) {
            onScrubEnd(previous.startSeconds, null)
        }
    }
    const replay = useCallback((): void => {
        setEnded(false)
        endedRef.current = false
        setCountdownCancelled(false)
        seekSession(unitRef.current === 'moment' ? domainRef.current.start : 0)
        play()
    }, [seekSession, play])
    const advance = useCallback((): void => onAdvance(index), [onAdvance, index])

    const scrubberBottom = Math.max(insets.bottom - 8, 10)
    // Room for the time labels that show above the bar when it is paused, ended or dragged.
    const captionBottom = scrubberBottom + 52
    const flag = countryFlag(recording.countryCode)
    const ago = recording.startedAt ? formatRelativeAgo(recording.startedAt, new Date()) : null
    const anchorColor =
        moment.kind === 'exception' ? tickColors.error : moment.kind === 'key' ? tickColors.key : tickColors.rage
    const hasMoment = moment.kind !== 'start'
    const [scrubbingUI, setScrubbingUI] = useState(false)
    const chromeHidden = holding || scrubbingUI
    // A hold or a scrub hides the chrome. A vertical drag of the feed dims it to half, through `scrollFade`.
    const shown = useSharedValue(1)
    useEffect(() => {
        shown.value = withTiming(chromeHidden ? 0 : 1, { duration: chromeHidden ? 120 : 180 })
    }, [chromeHidden, shown])
    const captionStyle = useAnimatedStyle(() => ({ opacity: shown.value * scrollFade.value }))
    // During a hold the rail stays, and fades every button but Speed itself.
    const railStyle = useAnimatedStyle(() => ({ opacity: (scrubbingUI ? shown.value : 1) * scrollFade.value }))
    useEffect(() => {
        if (webError) {
            trackFeedLoadFailed({ sessionId, message: webError })
        }
    }, [webError, sessionId])

    return (
        <View style={[styles.card, { width, height }]} testID={`feed-card-${index}`}>
            <View style={StyleSheet.absoluteFill}>
                {posterUri ? (
                    <Image
                        source={{ uri: posterUri }}
                        style={StyleSheet.absoluteFill}
                        resizeMode="cover"
                        blurRadius={36}
                        accessibilityIgnoresInvertColors
                    />
                ) : null}
                <View style={[StyleSheet.absoluteFill, styles.ambientDim]} />
                <View
                    style={[
                        styles.frame,
                        { top: frame.top, height: frame.height, left: frame.left, width: frame.width },
                        framed && styles.framedPhone,
                    ]}
                >
                    {web ? <ReplayWebView player={web} style={StyleSheet.absoluteFill} /> : null}
                    {video ? (
                        <VideoView
                            player={video}
                            style={StyleSheet.absoluteFill}
                            nativeControls={false}
                            contentFit="contain"
                            allowsPictureInPicture={false}
                            onFirstFrameRender={() => setFirstFrame(true)}
                            testID={active ? 'feed-video' : undefined}
                        />
                    ) : null}
                    <Animated.View style={[StyleSheet.absoluteFill, posterStyle]} pointerEvents="none">
                        {posterUri ? (
                            <Image
                                source={{ uri: posterUri }}
                                style={StyleSheet.absoluteFill}
                                resizeMode="contain"
                                accessibilityIgnoresInvertColors
                            />
                        ) : (
                            <View style={[StyleSheet.absoluteFill, styles.dimFrame]} />
                        )}
                        {webPlayer && !webError ? (
                            <View style={[StyleSheet.absoluteFill, styles.loading]}>
                                <ActivityIndicator
                                    size="small"
                                    color={feedColors.textSoft}
                                    accessibilityLabel="Loading the recording"
                                    testID={active ? 'feed-loading' : undefined}
                                />
                            </View>
                        ) : null}
                    </Animated.View>
                </View>
            </View>
            <View style={[styles.fadeTop, { height: insets.top + 110 }]} pointerEvents="none">
                <FadeEdge direction="down" solid={0} color="#000000" opacity={0.55} />
            </View>
            <View style={[styles.fadeBottom, { height: height * 0.46 }]} pointerEvents="none">
                <FadeEdge direction="up" solid={0.1} color="#000000" opacity={0.78} curve="smooth" />
            </View>

            <GestureDetector gesture={gesture.video}>
                <View style={StyleSheet.absoluteFill} collapsable={false} />
            </GestureDetector>

            {webPlayer && webError ? (
                <View style={[styles.ladder, { top: frame.top, height: frame.height }]} pointerEvents="box-none">
                    <View style={styles.errorPanel} testID={active ? 'feed-load-error' : undefined}>
                        <WarningIcon size={22} color={feedColors.text} />
                        <Text style={styles.errorTitle}>Could not load this recording</Text>
                        <View style={styles.errorActions}>
                            <Pressable44
                                onPress={() => web?.retry()}
                                accessibilityLabel="Try again"
                                style={styles.errorButton}
                                pressedStyle={styles.pressed}
                                testID="feed-load-retry"
                            >
                                <Text style={styles.errorButtonText}>Try again</Text>
                            </Pressable44>
                            {!demo ? (
                                <Pressable44
                                    onPress={() => onOpenWeb(item, startSeconds)}
                                    accessibilityRole="link"
                                    accessibilityLabel="Open in PostHog"
                                    style={styles.errorButton}
                                    pressedStyle={styles.pressed}
                                    testID="feed-load-open-web"
                                >
                                    <Text style={styles.errorButtonText}>Open in PostHog</Text>
                                    <ExternalLinkIcon size={13} color={feedColors.text} />
                                </Pressable44>
                            ) : null}
                        </View>
                    </View>
                </View>
            ) : null}

            {ladder ? (
                <View style={[styles.ladder, { top: frame.top, height: frame.height }]} pointerEvents="box-none">
                    <RenderLadder
                        state={ladder}
                        onPlay={() => requestRender('tap')}
                        onRetry={() => requestRender('tap', videoLoadFailed)}
                        onOpenWeb={() => onOpenWeb(item, startSeconds)}
                        onCheckAgain={onRecheck}
                        nextReady={
                            nextReady ? { title: nextReady.title, onPress: () => onJumpTo(nextReady.index) } : null
                        }
                    />
                </View>
            ) : null}

            {active && paused && showVideo && !ended ? (
                <View
                    style={[styles.pausedGlyph, { top: frame.top + frame.height / 2 - 34, left: width / 2 - 34 }]}
                    pointerEvents="none"
                >
                    <PlayIcon size={28} color={feedColors.text} />
                </View>
            ) : null}

            {toast ? (
                <Animated.View
                    key={toast.id}
                    entering={FadeIn.duration(140)}
                    exiting={FadeOut.duration(180)}
                    style={[styles.toast, { top: insets.top + 88 }]}
                    pointerEvents="none"
                    testID="feed-toast"
                >
                    <Text style={styles.toastText} numberOfLines={2}>
                        {toast.text}
                    </Text>
                </Animated.View>
            ) : null}

            <Animated.View
                style={[styles.rail, { bottom: captionBottom }, railStyle]}
                pointerEvents={chromeHidden ? 'none' : 'box-none'}
            >
                <FeedRail
                    speed={playbackRate(settings.speed, holdNow, lock)}
                    speedOn={holding}
                    speedOnly={holding}
                    onSpeed={onSpeed}
                    onChat={demo ? undefined : () => onChat(item)}
                    onShare={demo ? undefined : () => onShare(item, Math.max(0, Math.floor(position.value)))}
                />
            </Animated.View>

            <Animated.View
                style={[styles.caption, { bottom: captionBottom }, captionStyle]}
                pointerEvents={chromeHidden ? 'none' : 'box-none'}
            >
                <Pressable
                    onPress={() => onInfo(item, timeline, position.value)}
                    accessibilityRole="button"
                    accessibilityLabel={`${itemTitle(item)}. Opens Info`}
                    testID={active ? 'feed-caption' : undefined}
                >
                    <Text style={styles.person} numberOfLines={1}>
                        {[flag, recording.personLabel].filter(Boolean).join(' ')}
                        {ago ? <Text style={styles.personAgo}>{` · ${ago}`}</Text> : null}
                    </Text>
                    {unit === 'moment' && hasMoment ? (
                        <View style={styles.anchorRow}>
                            <View style={[styles.anchorDot, { backgroundColor: anchorColor }]} />
                            <Text style={styles.anchor} numberOfLines={1}>
                                {moment.label}
                            </Text>
                            <Text style={styles.anchorTime}>{`· ${formatOffset(moment.anchorSeconds * 1000)}`}</Text>
                        </View>
                    ) : null}
                    <Text style={styles.title} numberOfLines={2}>
                        {itemTitle(item)}
                    </Text>
                    <View style={styles.summaryRow}>
                        <Text style={[styles.summary, !summary?.text && styles.summaryNone]} numberOfLines={1}>
                            {summary?.text ?? 'No summary yet'}
                        </Text>
                        <Text style={styles.more}>more</Text>
                    </View>
                </Pressable>
            </Animated.View>

            <View style={[styles.scrubber, { bottom: scrubberBottom }]} pointerEvents="box-none">
                <FeedScrubber
                    start={domain.start}
                    end={domain.end}
                    rangeStart={rangeStart}
                    rangeEnd={rangeEnd}
                    position={position}
                    ticks={ticks}
                    marksShown={marksShown}
                    measured={active}
                    expanded={(paused && active) || ended}
                    leftLabel={unit === 'moment' ? signed(domain.start - moment.anchorSeconds) : formatOffset(0)}
                    rightLabel={
                        unit === 'moment'
                            ? signed(domain.end - moment.anchorSeconds)
                            : formatOffset(durationSeconds * 1000)
                    }
                    onScrubStart={() => {
                        setScrubbingUI(true)
                        onScrubStart()
                    }}
                    onScrub={onScrub}
                    onScrubCancel={cancelScrub}
                    onScrubEnd={(seconds, tick) => {
                        setScrubbingUI(false)
                        onScrubEnd(seconds, tick)
                    }}
                />
            </View>

            {active && ended ? (
                <GestureDetector gesture={gesture.panel}>
                    <View style={styles.upNext} pointerEvents="box-none">
                        <UpNextCard
                            next={next}
                            countdown={settings.autoplayNext && next !== null && !countdownCancelled}
                            onPlay={advance}
                            onCancel={() => setCountdownCancelled(true)}
                            onReplay={replay}
                        />
                    </View>
                </GestureDetector>
            ) : null}
        </View>
    )
}

function sameEntry(a: FeedCardEntry, b: FeedCardEntry): boolean {
    return (
        a.key === b.key &&
        a.index === b.index &&
        a.ordinal === b.ordinal &&
        a.first === b.first &&
        a.item === b.item &&
        a.moments === b.moments
    )
}

function sameUpNext(a: UpNextInfo | null, b: UpNextInfo | null): boolean {
    return (
        a?.title === b?.title &&
        a?.person === b?.person &&
        a?.durationSeconds === b?.durationSeconds &&
        a?.sameRecording === b?.sameRecording
    )
}

/** The screen re-renders on every page change; a card re-renders only when something it shows changed. */
export const FeedCard = memo(FeedCardBody, (previous, next) => {
    for (const key of Object.keys(next) as (keyof FeedCardProps)[]) {
        if (key === 'pool') {
            const a = previous.pool
            const b = next.pool
            if (a?.player !== b?.player || a?.key !== b?.key || a?.loaded !== b?.loaded) {
                return false
            }
        } else if (key === 'insets') {
            if (previous.insets.top !== next.insets.top || previous.insets.bottom !== next.insets.bottom) {
                return false
            }
        } else if (key === 'entry') {
            if (!sameEntry(previous.entry, next.entry)) {
                return false
            }
        } else if (key === 'next') {
            if (!sameUpNext(previous.next, next.next)) {
                return false
            }
        } else if (key === 'startAt') {
            if (previous.startAt?.id !== next.startAt?.id) {
                return false
            }
        } else if (key === 'nextReady') {
            if (
                previous.nextReady?.index !== next.nextReady?.index ||
                previous.nextReady?.title !== next.nextReady?.title
            ) {
                return false
            }
        } else if (previous[key] !== next[key]) {
            return false
        }
    }
    return true
})

const useStyles = createStyles(() => ({
    card: {
        backgroundColor: feedColors.stage,
        overflow: 'hidden',
    },
    ambientDim: {
        backgroundColor: feedColors.ambientDim,
    },
    frame: {
        position: 'absolute',
        backgroundColor: feedColors.stage,
        overflow: 'hidden',
    },
    framedPhone: {
        borderRadius: 22,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
    },
    dimFrame: {
        backgroundColor: '#15161A',
    },
    loading: {
        alignItems: 'center',
        justifyContent: 'center',
    },
    errorPanel: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        paddingHorizontal: 24,
        backgroundColor: 'rgba(0,0,0,0.55)',
    },
    errorTitle: {
        fontSize: 15,
        fontWeight: '700',
        color: feedColors.text,
        textAlign: 'center',
    },
    errorActions: {
        flexDirection: 'row',
        gap: 8,
    },
    errorButton: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 6,
        height: 34,
        paddingHorizontal: 14,
        borderRadius: 17,
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
    },
    errorButtonText: {
        fontSize: 13,
        fontWeight: '600',
        color: feedColors.text,
    },
    pressed: {
        opacity: 0.8,
    },
    fadeTop: {
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
    },
    fadeBottom: {
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
    },
    ladder: {
        position: 'absolute',
        left: 0,
        right: 0,
    },
    pausedGlyph: {
        position: 'absolute',
        width: 68,
        height: 68,
        borderRadius: 34,
        alignItems: 'center',
        justifyContent: 'center',
        paddingLeft: 4,
        backgroundColor: feedColors.glass,
    },
    toast: {
        position: 'absolute',
        alignSelf: 'center',
        maxWidth: 320,
        paddingVertical: 8,
        paddingHorizontal: 14,
        borderRadius: 18,
        backgroundColor: feedColors.glassStrong,
        borderWidth: 1,
        borderColor: feedColors.glassBorder,
    },
    toastText: {
        fontSize: 14,
        fontWeight: '600',
        color: feedColors.text,
        textAlign: 'center',
    },
    rail: {
        position: 'absolute',
        right: 4,
    },
    caption: {
        position: 'absolute',
        left: 16,
        right: 100,
    },
    person: {
        fontSize: 14,
        fontWeight: '700',
        color: feedColors.text,
        ...feedTextShadow,
    },
    personAgo: {
        fontWeight: '500',
        color: feedColors.textMuted,
    },
    title: {
        marginTop: 4,
        fontSize: 17,
        fontWeight: '700',
        lineHeight: 22,
        color: feedColors.text,
        ...feedTextShadow,
    },
    summaryRow: {
        flexDirection: 'row',
        alignItems: 'baseline',
        gap: 6,
        marginTop: 3,
    },
    summary: {
        flexShrink: 1,
        fontSize: 14,
        lineHeight: 19,
        color: feedColors.textMuted,
        ...feedTextShadow,
    },
    summaryNone: {
        color: feedColors.textFaint,
    },
    more: {
        fontSize: 14,
        fontWeight: '700',
        color: feedColors.text,
        ...feedTextShadow,
    },
    anchorRow: {
        flexDirection: 'row',
        alignItems: 'center',
        gap: 7,
        marginTop: 4,
    },
    anchorDot: {
        width: 8,
        height: 8,
        borderRadius: 4,
    },
    anchor: {
        flexShrink: 1,
        fontSize: 14,
        fontWeight: '600',
        color: '#FFD2B8',
        ...feedTextShadow,
    },
    anchorTime: {
        fontSize: 14,
        fontWeight: '500',
        color: feedColors.textMuted,
        ...feedTextShadow,
    },
    scrubber: {
        position: 'absolute',
        left: 16,
        right: 16,
    },
    upNext: {
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        left: 0,
        alignItems: 'center',
        justifyContent: 'center',
    },
}))
