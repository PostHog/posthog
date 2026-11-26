import { useVideoPlayer, VideoView } from 'expo-video'
import { type ReactElement, useCallback, useEffect, useRef, useState } from 'react'
import { ActivityIndicator, AppState, Modal, Platform, Text, View } from 'react-native'
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context'

import type { ReplayVideoExportContext, ReplayVideoSource } from '@/api/replayVideo'
import { CloseIcon } from '@/ui/icons/CloseIcon'
import { RecordingIcon } from '@/ui/icons/RecordingIcon'
import { WarningIcon } from '@/ui/icons/WarningIcon'
import { Pressable44 } from '@/ui/Pressable44'
import { StateView } from '@/ui/StateView'
import { createStyles, useColors } from '@/ui/theme'
import { iconSizes, layout, radii, type } from '@/ui/tokens'

import {
    type ReplayVideoFailureKind,
    trackReplayVideoClosed,
    trackReplayVideoFailed,
    trackReplayVideoReady,
    trackReplayVideoRequested,
} from '../replayAnalytics'
import { formatOffset } from '../sessionAdapters'
import { type ReplayVideoState, type UseReplayVideo, useReplayVideo } from './useReplayVideo'
import { useReplayVideoSource } from './useReplayVideoSource'
import { videoSecondsForSessionSeconds } from './videoTime'

interface ReplayVideoPlayerProps {
    sessionId: string
    durationSeconds: number | null
    /** Seconds into the session where playback starts. */
    seconds: number
    onClose: () => void
    /** Opens the recording in the web player. Null when the app has no web URL for it. */
    onOpenWeb: (() => void) | null
}

export function ReplayVideoPlayer(props: ReplayVideoPlayerProps): ReactElement {
    return (
        <Modal visible animationType="slide" presentationStyle="fullScreen" onRequestClose={props.onClose}>
            <SafeAreaProvider>
                <PlayerScreen {...props} />
            </SafeAreaProvider>
        </Modal>
    )
}

function PlayerScreen({ onClose, ...props }: ReplayVideoPlayerProps): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    const insets = useSafeAreaInsets()
    return (
        <View
            style={[
                styles.screen,
                { paddingTop: Math.max(insets.top, layout.minTopInset), paddingBottom: insets.bottom },
            ]}
        >
            <View style={styles.header}>
                <Text style={styles.title} accessibilityRole="header" numberOfLines={1}>
                    Session replay
                </Text>
                <Pressable44
                    onPress={onClose}
                    accessibilityLabel="Close"
                    pressedBackground={colors.sunken}
                    style={styles.close}
                    testID="replay-video-close"
                >
                    <CloseIcon size={iconSizes.control} color={colors.ink} />
                </Pressable44>
            </View>
            {Platform.OS === 'web' ? <NativeOnly onOpenWeb={props.onOpenWeb} /> : <VideoBody {...props} />}
        </View>
    )
}

function VideoBody({
    sessionId,
    durationSeconds,
    seconds,
    onOpenWeb,
}: Omit<ReplayVideoPlayerProps, 'onClose'>): ReactElement {
    const video = useReplayVideo({ sessionId, durationSeconds })
    const { state } = video
    // Tied to the state that failed, so the old source never plays again and the next report from the hook clears it.
    const [failedState, setFailedState] = useState<ReplayVideoState | null>(null)
    const playbackFailed = failedState === state
    const resumeAt = useRef<number | null>(null)
    const onPlaybackError = useCallback(
        (currentTime: number): void => {
            resumeAt.current = currentTime
            setFailedState(state)
        },
        [state]
    )
    useRequestWhileMounted(video)
    useVideoAnalytics(sessionId, state, playbackFailed)

    if (playbackFailed) {
        return (
            <VideoError
                kind="playback"
                message="Couldn't play this video. Try again."
                onRetry={video.retry}
                onOpenWeb={onOpenWeb}
            />
        )
    }
    switch (state.status) {
        case 'idle':
        case 'checking':
            return <Preparing startedAt={null} />
        case 'preparing':
            return <Preparing startedAt={state.startedAt} />
        case 'ready':
            return (
                <ReadyVideo
                    key={state.exportId}
                    exportId={state.exportId}
                    source={state.source}
                    context={state.context}
                    seconds={seconds}
                    resumeAt={resumeAt.current}
                    onPlaybackError={onPlaybackError}
                />
            )
        case 'error':
            return <VideoError kind={state.kind} message={state.message} onRetry={video.retry} onOpenWeb={onOpenWeb} />
    }
}

/** A lookup that finds a finished video takes a moment, so the render explanation waits for an actual render. */
function Preparing({ startedAt }: { startedAt: number | null }): ReactElement {
    const styles = useStyles()
    const colors = useColors()
    return (
        <View style={styles.state} testID="replay-video-preparing">
            <ActivityIndicator color={colors.ink} />
            <Text style={styles.stateTitle}>Preparing video</Text>
            {startedAt !== null ? (
                <>
                    <Text style={styles.stateMessage}>
                        PostHog is rendering this recording as a video. This usually takes a few minutes the first time.
                        You can close this and come back.
                    </Text>
                    <Elapsed startedAt={startedAt} />
                </>
            ) : null}
        </View>
    )
}

function Elapsed({ startedAt }: { startedAt: number }): ReactElement {
    const styles = useStyles()
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        const timer = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(timer)
    }, [])
    return <Text style={styles.elapsed}>{`${formatOffset(now - startedAt)} elapsed`}</Text>
}

interface ReadyVideoProps {
    exportId: number
    resumeAt: number | null
    source: ReplayVideoSource
    context: ReplayVideoExportContext | undefined
    seconds: number
    onPlaybackError: (currentTime: number) => void
}

function ReadyVideo({ exportId, source, context, seconds, resumeAt, onPlaybackError }: ReadyVideoProps): ReactElement {
    const styles = useStyles()
    const startAt = resumeAt ?? videoSecondsForSessionSeconds(seconds, context)
    const player = useVideoPlayer(source, (created) => {
        created.currentTime = startAt
        created.play()
    })
    const inPictureInPicture = useRef(false)
    useReplayVideoSource(player, exportId, source, onPlaybackError)
    // expo-video pauses on its own when the app goes to the background. iOS also has `inactive` (Control Center, the
    // app switcher), which it ignores. Picture in Picture keeps playing in both cases.
    useEffect(() => {
        const subscription = AppState.addEventListener('change', (next) => {
            if (next === 'inactive' && !inPictureInPicture.current) {
                player.pause()
            }
        })
        return () => subscription.remove()
    }, [player])
    return (
        <View style={styles.body}>
            <View style={styles.videoFrame}>
                <VideoView
                    player={player}
                    style={styles.video}
                    nativeControls
                    contentFit="contain"
                    fullscreenOptions={{ enable: true }}
                    allowsPictureInPicture
                    onPictureInPictureStart={() => {
                        inPictureInPicture.current = true
                    }}
                    onPictureInPictureStop={() => {
                        inPictureInPicture.current = false
                    }}
                    testID="replay-video-view"
                />
            </View>
            {context?.truncated ? (
                <Text style={styles.note} testID="replay-video-truncated">
                    This video stops early because the recording was too long to render in full.
                </Text>
            ) : null}
        </View>
    )
}

/** Retrying cannot fix these, so the web player is the only action offered. */
const FINAL_FAILURES: ReadonlySet<ReplayVideoFailureKind> = new Set(['too_long', 'limit_reached', 'missing_scope'])

interface VideoErrorProps {
    kind: ReplayVideoFailureKind
    message: string
    onRetry: () => void
    onOpenWeb: (() => void) | null
}

function VideoError({ kind, message, onRetry, onOpenWeb }: VideoErrorProps): ReactElement {
    const colors = useColors()
    const icon = <WarningIcon size={iconSizes.empty} color={colors.tertiary} />
    const webLabel = onOpenWeb ? 'Open in PostHog' : undefined
    if (FINAL_FAILURES.has(kind)) {
        return (
            <StateView
                icon={icon}
                title="Couldn't play this recording"
                message={message}
                actionLabel={webLabel}
                onAction={onOpenWeb ?? undefined}
                testID="replay-video-error"
            />
        )
    }
    return (
        <StateView
            icon={icon}
            title="Couldn't play this recording"
            message={message}
            actionLabel="Try again"
            onAction={onRetry}
            secondaryActionLabel={webLabel}
            onSecondaryAction={onOpenWeb ?? undefined}
            testID="replay-video-error"
        />
    )
}

function NativeOnly({ onOpenWeb }: { onOpenWeb: (() => void) | null }): ReactElement {
    const colors = useColors()
    return (
        <StateView
            icon={<RecordingIcon size={iconSizes.empty} color={colors.tertiary} />}
            title="Playback is available in the mobile app"
            message={onOpenWeb ? 'Open this recording in PostHog to watch it in your browser.' : undefined}
            actionLabel={onOpenWeb ? 'Open in PostHog' : undefined}
            onAction={onOpenWeb ?? undefined}
            testID="replay-video-web"
        />
    )
}

/** The hook's callbacks can change identity between renders, so a ref keeps this to one start and one reset. */
function useRequestWhileMounted(video: UseReplayVideo): void {
    const latest = useRef(video)
    useEffect(() => {
        latest.current = video
    })
    useEffect(() => {
        latest.current.start()
        return () => latest.current.reset()
    }, [])
}

function useVideoAnalytics(sessionId: string, state: ReplayVideoState, playbackFailed: boolean): void {
    const lastStatus = useRef<ReplayVideoState['status']>('idle')
    const closingStatus = useRef<ReplayVideoState['status']>('idle')
    useEffect(() => {
        const previous = lastStatus.current
        lastStatus.current = state.status
        if (previous === state.status) {
            return
        }
        if ((previous === 'idle' || previous === 'error') && state.status !== 'idle') {
            trackReplayVideoRequested(sessionId)
        }
        if (state.status === 'ready') {
            trackReplayVideoReady(sessionId, { waitedMs: state.waitedMs, reused: state.reused })
        } else if (state.status === 'error') {
            trackReplayVideoFailed(sessionId, state.kind)
        }
    }, [sessionId, state])
    useEffect(() => {
        if (playbackFailed) {
            trackReplayVideoFailed(sessionId, 'playback')
        }
    }, [sessionId, playbackFailed])
    useEffect(() => {
        closingStatus.current = playbackFailed ? 'error' : state.status
    }, [state.status, playbackFailed])
    useEffect(() => () => trackReplayVideoClosed(sessionId, { status: closingStatus.current }), [sessionId])
}

const useStyles = createStyles(({ colors }) => ({
    screen: {
        flex: 1,
        backgroundColor: colors.background,
    },
    header: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        paddingHorizontal: layout.detailGutter,
        paddingVertical: 8,
    },
    title: {
        ...type.sheetTitle,
        color: colors.ink,
        flexShrink: 1,
    },
    close: {
        width: 44,
        height: 44,
        borderRadius: radii.pill,
        borderWidth: 1,
        borderColor: colors.border,
        alignItems: 'center',
        justifyContent: 'center',
    },
    body: {
        flex: 1,
    },
    videoFrame: {
        flex: 1,
        backgroundColor: colors.media,
    },
    video: {
        flex: 1,
    },
    note: {
        ...type.meta,
        color: colors.secondary,
        paddingHorizontal: layout.detailGutter,
        paddingTop: 12,
        paddingBottom: 4,
    },
    state: {
        flex: 1,
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        paddingHorizontal: 28,
        paddingVertical: 48,
    },
    stateTitle: {
        ...type.sheetTitleLarge,
        color: colors.ink,
        textAlign: 'center',
        marginTop: 6,
    },
    stateMessage: {
        ...type.bodySmall,
        color: colors.muted,
        textAlign: 'center',
    },
    elapsed: {
        ...type.meta,
        color: colors.tertiary,
        textAlign: 'center',
        fontVariant: ['tabular-nums'],
    },
}))
