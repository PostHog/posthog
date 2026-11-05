import { act, fireEvent, render, screen } from '@testing-library/react-native'
import { useVideoPlayer, type VideoPlayer } from 'expo-video'
import type { ReactElement } from 'react'
import { AppState, type AppStateStatus } from 'react-native'

import { ApiError } from '@/api/client'
import { type ReplayVideoExportContext, resolveReplayVideoSource } from '@/api/replayVideo'
import { TransportError } from '@/api/transport'
import { type ReplayVideoState, useReplayVideo } from '@/features/replay/video/useReplayVideo'
import { videoSecondsForSessionSeconds } from '@/features/replay/video/videoTime'

import { ReplayVideoPlayer } from './ReplayVideoPlayer'

jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('@/api/replayVideo', () => ({
    ...jest.requireActual('@/api/replayVideo'),
    resolveReplayVideoSource: jest.fn(),
}))
jest.mock('@/features/replay/video/useReplayVideo', () => ({ useReplayVideo: jest.fn() }))
jest.mock('@/features/replay/video/videoTime', () => ({ videoSecondsForSessionSeconds: jest.fn(() => 42) }))
// The native view has no Jest renderer, so a plain View keeps the props, the player among them, for the test to read.
jest.mock('expo-video', () => {
    const { createElement } = jest.requireActual<typeof import('react')>('react')
    const { View } = jest.requireActual<typeof import('react-native')>('react-native')
    return {
        ...jest.requireActual('expo-video'),
        useVideoPlayer: jest.fn(jest.requireActual('expo-video').useVideoPlayer),
        VideoView: (props: Record<string, unknown>): ReactElement => createElement(View, props),
    }
})

const controls = { start: jest.fn(), retry: jest.fn(), reset: jest.fn() }

function renderPlayer(state: ReplayVideoState): {
    onOpenWeb: jest.Mock
    unmount: () => void
    updateState: (next: ReplayVideoState) => void
} {
    jest.mocked(useReplayVideo).mockReturnValue({ state, ...controls })
    const onOpenWeb = jest.fn()
    const element = (): ReactElement => (
        <ReplayVideoPlayer
            sessionId="session-1"
            durationSeconds={600}
            seconds={90}
            onClose={jest.fn()}
            onOpenWeb={onOpenWeb}
        />
    )
    const { unmount, rerender } = render(element())
    return {
        onOpenWeb,
        unmount,
        updateState: (next) => {
            jest.mocked(useReplayVideo).mockReturnValue({ state: next, ...controls })
            rerender(element())
        },
    }
}

describe('ReplayVideoPlayer', () => {
    afterEach(() => {
        jest.useRealTimers()
        jest.clearAllMocks()
        jest.restoreAllMocks()
    })

    test('a render in progress explains the wait and counts the time waited', () => {
        jest.useFakeTimers()
        const { unmount } = renderPlayer({
            status: 'preparing',
            exportId: 7,
            startedAt: Date.now() - 84_000,
            reused: false,
        })

        expect(controls.start).toHaveBeenCalledTimes(1)
        expect(screen.getByText(/PostHog is rendering this recording as a video/)).toBeTruthy()
        expect(screen.getByText('1:24 elapsed')).toBeTruthy()
        act(() => jest.advanceTimersByTime(1000))
        expect(screen.getByText('1:25 elapsed')).toBeTruthy()

        unmount()
        expect(controls.reset).toHaveBeenCalledTimes(1)
    })

    test('a ready video plays from the session offset mapped onto the video, and a player error offers a retry', () => {
        const context: ReplayVideoExportContext = { video_duration_s: 300, truncated: true }
        renderPlayer({
            status: 'ready',
            exportId: 7,
            source: { uri: 'https://example.com/replay.mp4' },
            context,
            reused: true,
            waitedMs: 0,
        })

        const player = screen.getByTestId('replay-video-view').props.player as VideoPlayer
        expect(videoSecondsForSessionSeconds).toHaveBeenCalledWith(90, context)
        expect(player.currentTime).toBe(42)
        expect(player.playing).toBe(true)
        expect(screen.getByTestId('replay-video-truncated')).toBeTruthy()

        act(() => player.emit('statusChange', { status: 'error', error: { message: 'decode failed' } }))
        expect(screen.getByText("Couldn't play this video. Try again.")).toBeTruthy()
        fireEvent.press(screen.getByTestId('replay-video-error-action'))
        expect(controls.retry).toHaveBeenCalledTimes(1)
    })

    test('shows recovery actions when loading fails before the error listener mounts', () => {
        jest.mocked(useVideoPlayer).mockImplementationOnce((source, setup) => {
            const actual = jest.requireActual<typeof import('expo-video')>('expo-video').useVideoPlayer
            return actual(source, (player) => {
                setup?.(player)
                Object.defineProperty(player, 'status', { value: 'error', configurable: true })
            })
        })
        const { onOpenWeb } = renderPlayer({
            status: 'ready',
            exportId: 7,
            source: { uri: 'https://example.com/replay.mp4' },
            context: undefined,
            reused: true,
            waitedMs: 0,
        })
        expect(screen.getByText("Couldn't play this video. Try again.")).toBeTruthy()
        fireEvent.press(screen.getByTestId('replay-video-error-action'))
        expect(controls.retry).toHaveBeenCalledTimes(1)
        fireEvent.press(screen.getByText('Open in PostHog'))
        expect(onOpenWeb).toHaveBeenCalledTimes(1)
    })

    test.each([
        { trigger: 'timer', playing: true },
        { trigger: 'foreground', playing: false },
    ])('renews the URL on $trigger and preserves playback (playing=$playing)', async ({ trigger, playing }) => {
        jest.useFakeTimers()
        const appListeners: ((state: AppStateStatus) => void)[] = []
        jest.spyOn(AppState, 'addEventListener').mockImplementation((_type, listener) => {
            appListeners.push(listener)
            return { remove: jest.fn() }
        })
        const expiresAt = Date.now() + 61_000
        const fresh = { uri: 'https://example.com/replay.mp4?fresh=1', expiresAt: expiresAt + 3_600_000 }
        jest.mocked(resolveReplayVideoSource).mockResolvedValue(fresh)
        renderPlayer({
            status: 'ready',
            exportId: 7,
            source: { uri: 'https://example.com/replay.mp4', expiresAt },
            context: undefined,
            reused: true,
            waitedMs: 0,
        })
        const player = screen.getByTestId('replay-video-view').props.player as VideoPlayer
        player.currentTime = 173
        player.playbackRate = 1.5
        if (!playing) {
            player.pause()
        }
        const replace = jest.spyOn(player, 'replaceAsync')
        await act(async () => {
            if (trigger === 'timer') {
                await jest.advanceTimersByTimeAsync(1_000)
            } else {
                jest.setSystemTime(expiresAt + 1_000)
                appListeners.forEach((listener) => {
                    listener('active')
                })
            }
        })
        expect(resolveReplayVideoSource).toHaveBeenCalledTimes(1)
        expect(replace).toHaveBeenCalledWith(fresh)
        expect(player.currentTime).toBe(173)
        expect(player.playbackRate).toBe(1.5)
        expect(player.playing).toBe(playing)
        expect(screen.queryByTestId('replay-video-error')).toBeNull()
    })

    test.each([
        { error: new TransportError(), retryMs: 10_000 },
        { error: new ApiError(429, {}, new Headers({ 'Retry-After': '20' })), retryMs: 20_000 },
    ])('keeps buffered playback during transient renewal failures ($retryMs ms retry)', async ({ error, retryMs }) => {
        jest.useFakeTimers()
        const expiresAt = Date.now() + 61_000
        const fresh = { uri: 'https://example.com/replay.mp4?fresh=1', expiresAt: expiresAt + 3_600_000 }
        jest.mocked(resolveReplayVideoSource).mockRejectedValueOnce(error).mockResolvedValue(fresh)
        renderPlayer({
            status: 'ready',
            exportId: 7,
            source: { uri: 'https://example.com/replay.mp4', expiresAt },
            context: undefined,
            reused: true,
            waitedMs: 0,
        })
        const player = screen.getByTestId('replay-video-view').props.player as VideoPlayer
        player.currentTime = 173
        const replace = jest.spyOn(player, 'replaceAsync')
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1_000)
        })
        expect(screen.getByTestId('replay-video-view').props.player).toBe(player)
        expect(screen.queryByTestId('replay-video-error')).toBeNull()
        expect(replace).not.toHaveBeenCalled()
        expect(player.playing).toBe(true)
        player.currentTime = 183
        await act(async () => {
            await jest.advanceTimersByTimeAsync(retryMs - 1)
        })
        expect(resolveReplayVideoSource).toHaveBeenCalledTimes(1)
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1)
        })
        expect(replace).toHaveBeenCalledWith(fresh)
        expect(player.currentTime).toBe(183)
        expect(player.playing).toBe(true)
    })

    test('keeps the playhead when renewal fails and the user retries', async () => {
        jest.useFakeTimers()
        const ready: ReplayVideoState = {
            status: 'ready',
            exportId: 7,
            source: { uri: 'https://example.com/replay.mp4', expiresAt: Date.now() + 61_000 },
            context: undefined,
            reused: true,
            waitedMs: 0,
        }
        let failRenewal: (error: Error) => void = () => undefined
        jest.mocked(resolveReplayVideoSource).mockImplementation(
            () =>
                new Promise((_resolve, reject) => {
                    failRenewal = reject
                })
        )
        const { updateState } = renderPlayer(ready)
        const player = screen.getByTestId('replay-video-view').props.player as VideoPlayer
        player.currentTime = 173
        Object.defineProperty(player, 'status', { value: 'error', configurable: true })
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1_000)
        })
        player.currentTime = 183
        await act(async () => {
            failRenewal(new TransportError())
        })
        expect(screen.getByText("Couldn't play this video. Try again.")).toBeTruthy()
        fireEvent.press(screen.getByTestId('replay-video-error-action'))
        expect(controls.retry).toHaveBeenCalledTimes(1)
        updateState({ ...ready, source: { uri: 'https://example.com/replay.mp4?retry=1' } })
        const retried = screen.getByTestId('replay-video-view').props.player as VideoPlayer
        expect(retried.currentTime).toBe(183)
    })

    test('aborts renewal on close and ignores a late response', async () => {
        jest.useFakeTimers()
        let complete: (source: { uri: string }) => void = () => undefined
        jest.mocked(resolveReplayVideoSource).mockImplementation(
            () =>
                new Promise((resolve) => {
                    complete = resolve
                })
        )
        const { unmount } = renderPlayer({
            status: 'ready',
            exportId: 7,
            source: { uri: 'https://example.com/replay.mp4', expiresAt: Date.now() + 61_000 },
            context: undefined,
            reused: true,
            waitedMs: 0,
        })
        const player = screen.getByTestId('replay-video-view').props.player as VideoPlayer
        const replace = jest.spyOn(player, 'replaceAsync')
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1_000)
        })
        const signal = jest.mocked(resolveReplayVideoSource).mock.calls[0]?.[1]
        unmount()
        expect(signal?.aborted).toBe(true)
        await act(async () => {
            complete({ uri: 'https://example.com/replay.mp4?late=1' })
        })
        expect(replace).not.toHaveBeenCalled()
    })

    test.each([
        { kind: 'render_failed', primary: 'Try again', offersRetry: true },
        { kind: 'limit_reached', primary: 'Open in PostHog', offersRetry: false },
        { kind: 'missing_scope', primary: 'Open in PostHog', offersRetry: false },
    ] as const)('a $kind error leads with $primary', ({ kind, primary, offersRetry }) => {
        const { onOpenWeb } = renderPlayer({ status: 'error', kind, message: 'The server said no.' })

        expect(screen.getByText('The server said no.')).toBeTruthy()
        expect(screen.getByTestId('replay-video-error-action')).toHaveTextContent(primary)
        expect(screen.queryByText('Try again') !== null).toBe(offersRetry)
        fireEvent.press(screen.getByText('Open in PostHog'))
        expect(onOpenWeb).toHaveBeenCalledTimes(1)
    })
})
