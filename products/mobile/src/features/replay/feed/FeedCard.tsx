import { VideoView } from 'expo-video'
import { memo, type ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from 'react-native'
import { Gesture, GestureDetector } from 'react-native-gesture-handler'
import Animated, {
    Easing,
    FadeIn,
    FadeOut,
    useAnimatedStyle,
    useReducedMotion,
    useSharedValue,
    withSequence,
    withTiming,
} from 'react-native-reanimated'
import { scheduleOnRN } from 'react-native-worklets'

import { pickReusableExport } from '@/api/replayVideo'
import { formatRelativeAgo } from '@/lib/dates'
import { haptic } from '@/lib/haptics'
import { plural } from '@/model/adapters/text'
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
import { FeedScrubber, type ScrubberTick } from './FeedScrubber'
import { feedMoments, type RenderSpec, renderKey, renderViewport, sessionStartSeconds } from './feedAdapters'
import {
    trackFeedAutoAdvanced,
    trackFeedEventJump,
    trackFeedFullRecording,
    trackFeedHoldStarted,
    trackFeedItemShown,
    trackFeedLoadFailed,
    trackFeedSpeedLocked,
    trackFeedSpeedUnlocked,
} from './feedAnalytics'
import { armHold, beginHold, finishHold, holdHaptic, holdPull, useFeedHold } from './feedHoldStore'
import type { FeedEvent, FeedItem, FeedSettings, FeedSource, FeedTimeline, FeedUnit, Moment } from './feedModel'
import type { FeedPlayer, PoolPlayer } from './feedPlayer'
import { feedColors, feedTextShadow, type TickKind, tickColors } from './feedStyle'
import { HOLD_PULL, playbackRate } from './holdLock'
import { type LadderState, RenderLadder } from './RenderLadder'
import { startRender, useRenderQueue } from './renderQueue'
import { UpNextCard } from './UpNextCard'
import { useFeedTimeline } from './useFeed'
import type { PoolSource } from './usePlayerPool'

/** A card renders only after this long on screen, or on a tap of Play, so a swipe past never spends the video cap. */
export const DWELL_MS = 1500
const EMPTY_TIMELINE: FeedTimeline = { events: [], browser: null, os: null, viewport: null }
const JUMP_SECONDS = 10

export interface FeedCardHandle {
    seekToSession: (seconds: number) => void
    hold: (on: boolean) => void
    togglePause: () => void
    stepMoment: (direction: 1 | -1) => void
}

interface FeedCardProps {
    item: FeedItem
    index: number
    width: number
    height: number
    insets: { top: number; bottom: number }
    active: boolean
    near: boolean
    pool: PoolPlayer | null
    /** Plays the recording's snapshots in a WebView: no render, no export. */
    webPlayer: boolean
    unit: FeedUnit
    source: FeedSource
    settings: FeedSettings
    next: FeedItem | null
    nextReady: { index: number; title: string } | null
    onSource: (index: number, source: PoolSource | null) => void
    onAdvance: (index: number) => void
    onJumpTo: (index: number) => void
    onSpeed: () => void
    onShare: (item: FeedItem, seconds: number) => void
    onChat: (item: FeedItem) => void
    onInfo: (item: FeedItem, timeline: FeedTimeline | null) => void
    onOpenWeb: (item: FeedItem, seconds: number) => void
    onRecheck: () => void
    registerHandle: (index: number, handle: FeedCardHandle | null) => void
}

export function itemTitle(item: FeedItem): string {
    if (item.summary?.title) {
        return item.summary.title
    }
    const { clickCount, consoleErrorCount } = item.recording
    return ['Recording', plural(clickCount, 'click'), consoleErrorCount ? plural(consoleErrorCount, 'error') : null]
        .filter(Boolean)
        .join(' · ')
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
    item,
    index,
    width,
    height,
    insets,
    active,
    near,
    pool,
    webPlayer,
    unit: feedUnit,
    source,
    settings,
    next,
    nextReady,
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
    const reduceMotion = useReducedMotion()
    const { recording, summary } = item
    const { sessionId, durationSeconds } = recording
    const timeline = useFeedTimeline(item, near)
    const moments = useMemo(
        () => feedMoments(timeline ?? EMPTY_TIMELINE, summary, durationSeconds, settings, source),
        [timeline, summary, durationSeconds, settings, source]
    )
    const [momentIndex, setMomentIndex] = useState(0)
    // Full recording plays this card's whole recording while the feed keeps playing moments.
    const [fullOn, setFullOn] = useState(false)
    const unit: FeedUnit = feedUnit === 'moment' && fullOn ? 'session' : feedUnit
    const safeIndex = Math.min(momentIndex, moments.length - 1)
    const moment = moments[safeIndex] as Moment
    const domain =
        unit === 'moment' ? { start: moment.startSeconds, end: moment.endSeconds } : { start: 0, end: durationSeconds }
    const startSeconds = unit === 'moment' ? moment.startSeconds : sessionStartSeconds(moments, summary, settings)

    // Each card listens to its own two jobs only, so one render's progress does not re-render every card.
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
                known: item.exports,
                allowCreate: false,
                trigger: 'reuse',
                viewport: viewportRef.current,
            })
        }
    }, [near, key, recording.ongoing, item.exports, webPlayer])

    const canRender = !recording.ongoing && limitMessage === null && (spec.kind === 'full' || timeline !== null)
    const requestRender = useCallback(
        (trigger: 'dwell' | 'tap'): void => {
            if (!webPlayer) {
                startRender({
                    spec: specRef.current,
                    known: null,
                    allowCreate: true,
                    trigger,
                    viewport: viewportRef.current,
                })
            }
        },
        [webPlayer]
    )
    useEffect(() => {
        if (webPlayer || !active || job !== null || !canRender) {
            return undefined
        }
        const timer = setTimeout(() => requestRender('dwell'), DWELL_MS)
        return () => clearTimeout(timer)
    }, [webPlayer, active, job, canRender, requestRender])

    const ready = job?.state.status === 'ready' ? job.state : null
    const sourceKey = webPlayer ? `web:${sessionId}` : ready ? `${key}#${ready.exportId}` : null
    // biome-ignore lint/correctness/useExhaustiveDependencies: the key names the source; the object is new each render.
    useEffect(() => {
        if (!webPlayer) {
            onSource(index, ready && sourceKey ? { key: sourceKey, source: ready.source } : null)
        }
    }, [index, sourceKey, onSource, webPlayer])
    useEffect(() => () => onSource(index, null), [index, onSource])

    const loaded = pool !== null && pool.key === sourceKey && pool.loaded
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
    // A phone session fills the card, or with "Whole screen" sits between the chrome and the caption so nothing
    // covers its own header and tab bar. A desktop page is letterboxed a little above the middle.
    const framed = portrait && settings.phoneFit === 'whole'
    const bleed = portrait && !framed
    const frame = (() => {
        if (bleed) {
            return { top: 0, height, left: 0, width }
        }
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
    const [nowSeconds, setNowSeconds] = useState(startSeconds)
    const pendingSeek = useRef<number | null>(null)
    const scrubbing = useRef<{ wasPlaying: boolean } | null>(null)
    const domainRef = useRef(domain)
    domainRef.current = domain
    const unitRef = useRef(unit)
    unitRef.current = unit
    const overrideStart = useRef<number | null>(null)

    // biome-ignore lint/correctness/useExhaustiveDependencies: a new video means a new first frame.
    useEffect(() => {
        setFirstFrame(false)
    }, [sourceKey])

    const seekSession = useCallback(
        (seconds: number): void => {
            position.value = seconds
            setNowSeconds(seconds)
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

    const startKey = `${unit}:${moment.key}:${unit === 'session' ? startSeconds : ''}`
    // A WebView player loads only the blocks it needs, so it learns the window before the first seek reaches it.
    // biome-ignore lint/correctness/useExhaustiveDependencies: `startKey` names the window; the rest are read through refs.
    useEffect(() => {
        web?.prepare(
            overrideStart.current ?? startSeconds,
            unit === 'moment' ? domain.end : null,
            active && !pausedRef.current
        )
    }, [web, startKey])
    useEffect(() => {
        if (!web) {
            return undefined
        }
        setWebError(null)
        const frame = web.onFirstFrame(() => setFirstFrame(true))
        const status = web.addListener('statusChange', () =>
            setWebError(web.status === 'error' ? (web.errorMessage ?? "Couldn't play this recording.") : null)
        )
        return () => {
            frame.remove()
            status.remove()
        }
    }, [web])
    // biome-ignore lint/correctness/useExhaustiveDependencies: `startKey` names the start; the rest are read through refs.
    useEffect(() => {
        if (!player) {
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
        const start = overrideStart.current ?? startSeconds
        overrideStart.current = null
        seekSession(start)
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

    // Gestures and the end-of-window timer reach the newest handlers through this ref.
    const handlers = useRef<{
        togglePause: () => void
        jump: (direction: 1 | -1) => void
        holdStart: () => void
        holdEnd: (cancelled: boolean) => void
        stepMoment: (direction: 1 | -1) => void
    } | null>(null)

    const finishWindow = useCallback((): void => {
        if (endedRef.current || !player) {
            return
        }
        player.pause()
        if (unitRef.current === 'moment' && safeIndex < moments.length - 1) {
            trackFeedAutoAdvanced({ sessionId, to: 'moment', skipped: 0 })
            handlers.current?.stepMoment(1)
            return
        }
        endedRef.current = true
        setEnded(true)
        setCountdownCancelled(false)
    }, [player, safeIndex, moments.length, sessionId])

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
            setNowSeconds(Math.floor(seconds))
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

    const slide = useSharedValue(0)
    const fade = useSharedValue(1)
    const stepMoment = (direction: 1 | -1): void => {
        const target = Math.min(moments.length - 1, Math.max(0, safeIndex + direction))
        if (target === safeIndex) {
            return
        }
        haptic('selection')
        if (!reduceMotion) {
            slide.value = withSequence(
                withTiming(-direction * width * 0.18, { duration: 120 }),
                withTiming(direction * width * 0.18, { duration: 0 }),
                withTiming(0, { duration: 200, easing: Easing.out(Easing.cubic) })
            )
            fade.value = withSequence(withTiming(0.2, { duration: 120 }), withTiming(1, { duration: 200 }))
        }
        setEnded(false)
        endedRef.current = false
        setMomentIndex(target)
    }
    const stageStyle = useAnimatedStyle(() => ({ transform: [{ translateX: slide.value }], opacity: fade.value }))

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
        const result = finishHold(cancelled, settings.speed)
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

    handlers.current = { togglePause, jump, holdStart, holdEnd, stepMoment }
    const dispatch = useCallback(
        (action: 'toggle' | 'jump' | 'holdStart' | 'holdArm' | 'holdEnd' | 'step', value: number): void => {
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
            } else {
                current.stepMoment(value > 0 ? 1 : -1)
            }
        },
        []
    )
    const holdArmed = useSharedValue(false)
    const holdActive = useSharedValue(false)
    const canSwipeMoments = unit === 'moment' && moments.length > 1
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
        // A hold owns the finger once it starts, so its pull never pages the feed or swipes a moment.
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
        const swipe = Gesture.Pan()
            .enabled(canSwipeMoments)
            .activeOffsetX([-22, 22])
            .failOffsetY([-14, 14])
            .onUpdate((event) => {
                'worklet'
                slide.value = event.translationX * 0.35
            })
            .onEnd((event) => {
                'worklet'
                const far = Math.abs(event.translationX) > 64 || Math.abs(event.velocityX) > 600
                if (far) {
                    scheduleOnRN(dispatch, 'step', event.translationX < 0 ? 1 : -1)
                } else {
                    slide.value = withTiming(0, { duration: 160 })
                }
            })
        return Gesture.Race(swipe, Gesture.Exclusive(hold, doubleTap, singleTap))
    }, [width, canSwipeMoments, dispatch, slide, holdActive, holdArmed])

    const seekFromInfo = useCallback(
        (seconds: number): void => {
            if (unitRef.current === 'moment') {
                const inside = moments.findIndex((item) => seconds >= item.startSeconds && seconds <= item.endSeconds)
                if (inside >= 0) {
                    overrideStart.current = seconds
                    if (inside === safeIndex) {
                        seekSession(seconds)
                        overrideStart.current = null
                        play()
                    } else {
                        setMomentIndex(inside)
                    }
                    return
                }
                overrideStart.current = seconds
                setFullOn(true)
                return
            }
            seekSession(seconds)
            if (endedRef.current) {
                setEnded(false)
                endedRef.current = false
            }
            play()
        },
        [moments, safeIndex, seekSession, play]
    )
    useEffect(() => {
        if (!active) {
            return undefined
        }
        registerHandle(index, {
            seekToSession: seekFromInfo,
            hold: (on) => (on ? handlers.current?.holdStart() : handlers.current?.holdEnd(false)),
            togglePause: () => handlers.current?.togglePause(),
            stepMoment: (direction) => handlers.current?.stepMoment(direction),
        })
        return () => registerHandle(index, null)
    }, [active, index, registerHandle, seekFromInfo])

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
        return fromEvents
    }, [timeline, summary, domain.start, domain.end])

    const onScrubStart = useCallback((): void => {
        scrubbing.current = { wasPlaying: player?.playing ?? false }
        player?.pause()
    }, [player])
    const lastScrubSeek = useRef(0)
    const onScrub = useCallback(
        (seconds: number): void => {
            setNowSeconds(seconds)
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

    const nextInfo = useMemo(
        () =>
            next
                ? {
                      title: itemTitle(next),
                      person: next.recording.personLabel,
                      durationSeconds: next.recording.durationSeconds,
                  }
                : null,
        [next]
    )
    const replay = useCallback((): void => {
        setEnded(false)
        endedRef.current = false
        setCountdownCancelled(false)
        seekSession(unitRef.current === 'moment' ? domainRef.current.start : 0)
        play()
    }, [seekSession, play])
    const advance = useCallback((): void => onAdvance(index), [onAdvance, index])

    const scrubberBottom = Math.max(insets.bottom - 8, 10)
    const captionBottom = scrubberBottom + 40
    const flag = countryFlag(recording.countryCode)
    const ago = recording.startedAt ? formatRelativeAgo(recording.startedAt, new Date()) : null
    const anchorColor =
        moment.kind === 'exception' ? tickColors.error : moment.kind === 'key' ? tickColors.key : tickColors.rage
    const hasMoment = moment.kind !== 'start'
    const showDots = unit === 'moment' && moments.length > 1
    const [scrubbingUI, setScrubbingUI] = useState(false)
    const chromeHidden = holding || scrubbingUI
    const chromeStyle = useAnimatedStyle(
        () => ({ opacity: withTiming(chromeHidden ? 0 : 1, { duration: chromeHidden ? 120 : 180 }) }),
        [chromeHidden]
    )
    const toggleFull = (): void => {
        const next = !fullOn
        trackFeedFullRecording({ sessionId, on: next })
        haptic('selection')
        overrideStart.current = next ? position.value : null
        setEnded(false)
        endedRef.current = false
        setFullOn(next)
    }
    useEffect(() => {
        if (webError) {
            trackFeedLoadFailed({ sessionId, message: webError })
        }
    }, [webError, sessionId])
    const dotsTop = bleed ? null : frame.top + frame.height + 12

    return (
        <View style={[styles.card, { width, height }]} testID={`feed-card-${index}`}>
            <Animated.View style={[StyleSheet.absoluteFill, stageStyle]}>
                {!bleed && posterUri ? (
                    <Image
                        source={{ uri: posterUri }}
                        style={StyleSheet.absoluteFill}
                        resizeMode="cover"
                        blurRadius={36}
                        accessibilityIgnoresInvertColors
                    />
                ) : null}
                {!bleed ? <View style={[StyleSheet.absoluteFill, styles.ambientDim]} /> : null}
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
                            contentFit={bleed ? 'cover' : 'contain'}
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
                                resizeMode={bleed ? 'cover' : 'contain'}
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
            </Animated.View>
            <View style={[styles.fadeTop, { height: insets.top + 110 }]} pointerEvents="none">
                <FadeEdge direction="down" solid={0} color="#000000" opacity={0.55} />
            </View>
            <View style={[styles.fadeBottom, { height: height * 0.46 }]} pointerEvents="none">
                <FadeEdge direction="up" solid={0.1} color="#000000" opacity={0.78} curve="smooth" />
            </View>

            <GestureDetector gesture={gesture}>
                <View style={StyleSheet.absoluteFill} collapsable={false} />
            </GestureDetector>

            {webPlayer && webError ? (
                <View
                    style={[styles.ladder, { top: frame.top, height: bleed ? height * 0.62 : frame.height }]}
                    pointerEvents="box-none"
                >
                    <View style={styles.errorPanel} testID={active ? 'feed-load-error' : undefined}>
                        <WarningIcon size={22} color={feedColors.text} />
                        <Text style={styles.errorTitle}>Could not load this recording</Text>
                        <View style={styles.errorActions}>
                            <Pressable44
                                onPress={() => web?.restart()}
                                accessibilityLabel="Try again"
                                style={styles.errorButton}
                                pressedStyle={styles.pressed}
                                testID="feed-load-retry"
                            >
                                <Text style={styles.errorButtonText}>Try again</Text>
                            </Pressable44>
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
                        </View>
                    </View>
                </View>
            ) : null}

            {ladder ? (
                <View
                    style={[styles.ladder, { top: frame.top, height: bleed ? height * 0.62 : frame.height }]}
                    pointerEvents="box-none"
                >
                    <RenderLadder
                        state={ladder}
                        onPlay={() => requestRender('tap')}
                        onRetry={() => requestRender('tap')}
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

            {showDots ? (
                <Animated.View
                    style={[
                        styles.dots,
                        dotsTop === null ? { bottom: captionBottom + 132 } : { top: dotsTop },
                        chromeStyle,
                    ]}
                    pointerEvents="none"
                    testID="feed-moment-dots"
                >
                    {moments.map((entry, position) => (
                        <View key={entry.key} style={[styles.dot, position === safeIndex && styles.dotOn]} />
                    ))}
                </Animated.View>
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
                style={[styles.rail, { bottom: captionBottom }, scrubbingUI && chromeStyle]}
                pointerEvents={chromeHidden ? 'none' : 'box-none'}
            >
                <FeedRail
                    showFull={feedUnit === 'moment' && hasMoment}
                    fullOn={fullOn}
                    speed={playbackRate(settings.speed, holdNow, lock)}
                    speedOn={holding || lock !== null}
                    locked={lock !== null}
                    speedOnly={holding}
                    onFull={toggleFull}
                    onSpeed={onSpeed}
                    onChat={() => onChat(item)}
                    onShare={() => onShare(item, Math.max(0, Math.floor(position.value)))}
                />
            </Animated.View>

            <Animated.View
                style={[styles.caption, { bottom: captionBottom }, chromeStyle]}
                pointerEvents={chromeHidden ? 'none' : 'box-none'}
            >
                <Pressable
                    onPress={() => onInfo(item, timeline)}
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
                    position={position}
                    ticks={ticks}
                    expanded={(paused && active) || ended}
                    leftLabel={
                        unit === 'moment'
                            ? signed(domain.start - moment.anchorSeconds)
                            : formatOffset(nowSeconds * 1000)
                    }
                    rightLabel={
                        unit === 'moment'
                            ? signed(domain.end - moment.anchorSeconds)
                            : formatOffset(durationSeconds * 1000)
                    }
                    idleLabel={formatOffset(nowSeconds * 1000)}
                    onScrubStart={() => {
                        setScrubbingUI(true)
                        onScrubStart()
                    }}
                    onScrub={onScrub}
                    onScrubEnd={(seconds, tick) => {
                        setScrubbingUI(false)
                        onScrubEnd(seconds, tick)
                    }}
                />
            </View>

            {active && ended ? (
                <View style={styles.upNext} pointerEvents="box-none">
                    <UpNextCard
                        next={nextInfo}
                        countdown={settings.autoplayNext && nextInfo !== null && !countdownCancelled}
                        onPlay={advance}
                        onCancel={() => setCountdownCancelled(true)}
                        onReplay={replay}
                    />
                </View>
            ) : null}
        </View>
    )
}

function sameItemTitle(a: FeedItem | null, b: FeedItem | null): boolean {
    return a?.recording.sessionId === b?.recording.sessionId && a?.summary?.title === b?.summary?.title
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
        } else if (key === 'next') {
            if (!sameItemTitle(previous.next, next.next)) {
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
    dots: {
        position: 'absolute',
        alignSelf: 'center',
        flexDirection: 'row',
        alignItems: 'center',
        gap: 5,
        height: 12,
    },
    dot: {
        width: 6,
        height: 6,
        borderRadius: 3,
        backgroundColor: 'rgba(255,255,255,0.4)',
    },
    dotOn: {
        width: 14,
        backgroundColor: feedColors.text,
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
