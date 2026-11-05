import { act, fireEvent, render, screen } from '@testing-library/react-native'
import type { VideoPlayer } from 'expo-video'
import type { ReactElement } from 'react'

import type { ReplayVideoExportContext } from '@/api/replayVideo'
import { type ReplayVideoState, useReplayVideo } from '@/features/replay/video/useReplayVideo'
import { videoSecondsForSessionSeconds } from '@/features/replay/video/videoTime'

import { ReplayVideoPlayer } from './ReplayVideoPlayer'

jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('@/features/replay/video/useReplayVideo', () => ({ useReplayVideo: jest.fn() }))
jest.mock('@/features/replay/video/videoTime', () => ({ videoSecondsForSessionSeconds: jest.fn(() => 42) }))
// The native view has no Jest renderer, so a plain View keeps the props, the player among them, for the test to read.
jest.mock('expo-video', () => {
    const { createElement } = jest.requireActual<typeof import('react')>('react')
    const { View } = jest.requireActual<typeof import('react-native')>('react-native')
    return {
        ...jest.requireActual('expo-video'),
        VideoView: (props: Record<string, unknown>): ReactElement => createElement(View, props),
    }
})

const controls = { start: jest.fn(), retry: jest.fn(), reset: jest.fn() }

function renderPlayer(state: ReplayVideoState): { onOpenWeb: jest.Mock; unmount: () => void } {
    jest.mocked(useReplayVideo).mockReturnValue({ state, ...controls })
    const onOpenWeb = jest.fn()
    const { unmount } = render(
        <ReplayVideoPlayer
            sessionId="session-1"
            durationSeconds={600}
            seconds={90}
            onClose={jest.fn()}
            onOpenWeb={onOpenWeb}
        />
    )
    return { onOpenWeb, unmount }
}

describe('ReplayVideoPlayer', () => {
    afterEach(() => {
        jest.useRealTimers()
        jest.clearAllMocks()
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
