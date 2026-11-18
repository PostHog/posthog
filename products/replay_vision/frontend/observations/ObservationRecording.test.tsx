import { render } from '@testing-library/react'

import ObservationRecording from './ObservationRecording'

const mockSeekToTime = jest.fn()
const mockPlayer = jest.fn<JSX.Element, [unknown]>(() => <div data-attr="recording-player" />)
let mockSessionPlayerData: { start: { valueOf: () => number } | null; end: { valueOf: () => number } | null } | null
let mockCurrentTimestamp: number | undefined
let mockIsNotFound = false

jest.mock('kea', () => ({
    useValues: () => ({
        sessionPlayerData: mockSessionPlayerData,
        currentTimestamp: mockCurrentTimestamp,
        isNotFound: mockIsNotFound,
    }),
}))

jest.mock('scenes/session-recordings/player/SessionRecordingPlayer', () => ({
    SessionRecordingPlayer: (props: unknown) => mockPlayer(props),
}))

jest.mock('scenes/session-recordings/player/sessionRecordingMetaLogic', () => ({
    sessionRecordingMetaLogic: jest.fn(),
}))

jest.mock('scenes/session-recordings/player/sessionRecordingPlayerLogic', () => ({
    SessionRecordingPlayerMode: { Standard: 'standard' },
    sessionRecordingPlayerLogic: Object.assign(jest.fn(), {
        findMounted: () => ({ actions: { seekToTime: mockSeekToTime } }),
    }),
}))

describe('ObservationRecording', () => {
    beforeEach(() => {
        mockSeekToTime.mockClear()
        mockPlayer.mockClear()
        mockSessionPlayerData = null
        mockCurrentTimestamp = undefined
        mockIsNotFound = false
    })

    it('preserves player options and seeks once per citation after recording data arrives', () => {
        const props = { playerKey: 'player-example', sessionRecordingId: 'session-example', unavailable: null }
        const { rerender } = render(<ObservationRecording {...props} pendingSeek={null} />)
        expect(mockPlayer).toHaveBeenLastCalledWith({
            playerKey: props.playerKey,
            sessionRecordingId: props.sessionRecordingId,
            mode: 'standard',
            autoPlay: false,
            noBorder: true,
            noDock: true,
            withSidebar: true,
        })
        expect(mockSeekToTime).not.toHaveBeenCalled()

        const pendingSeek = { ms: 5000, trigger: 1 }
        rerender(<ObservationRecording {...props} pendingSeek={pendingSeek} />)
        expect(mockSeekToTime).not.toHaveBeenCalled()

        mockSessionPlayerData = { start: { valueOf: () => 1000 }, end: null }
        rerender(<ObservationRecording {...props} pendingSeek={pendingSeek} />)
        expect(mockSeekToTime).not.toHaveBeenCalled()

        mockSessionPlayerData = { start: null, end: { valueOf: () => 9000 } }
        rerender(<ObservationRecording {...props} pendingSeek={pendingSeek} />)
        expect(mockSeekToTime).not.toHaveBeenCalled()

        mockSessionPlayerData = { start: { valueOf: () => 1000 }, end: { valueOf: () => 9000 } }
        rerender(<ObservationRecording {...props} pendingSeek={pendingSeek} />)
        expect(mockSeekToTime).not.toHaveBeenCalled()

        mockCurrentTimestamp = 0
        rerender(<ObservationRecording {...props} pendingSeek={pendingSeek} />)
        expect(mockSeekToTime).toHaveBeenCalledTimes(1)
        expect(mockSeekToTime).toHaveBeenLastCalledWith(5000)

        mockSessionPlayerData = { start: { valueOf: () => 1000 }, end: { valueOf: () => 12000 } }
        mockCurrentTimestamp = 6000
        rerender(<ObservationRecording {...props} pendingSeek={pendingSeek} />)
        expect(mockSeekToTime).toHaveBeenCalledTimes(1)

        rerender(<ObservationRecording {...props} pendingSeek={{ ms: 5000, trigger: 2 }} />)
        expect(mockSeekToTime).toHaveBeenCalledTimes(2)
        expect(mockSeekToTime).toHaveBeenLastCalledWith(5000)

        rerender(<ObservationRecording {...props} pendingSeek={{ ms: 7000, trigger: 3 }} />)
        expect(mockSeekToTime).toHaveBeenCalledTimes(3)
        expect(mockSeekToTime).toHaveBeenLastCalledWith(7000)

        rerender(<ObservationRecording {...props} pendingSeek={null} />)
        expect(mockSeekToTime).toHaveBeenCalledTimes(3)
    })

    it('swaps the player for the unavailable message once the recording turns out to be gone', () => {
        mockIsNotFound = true
        const { getByText } = render(
            <ObservationRecording
                playerKey="player-example"
                sessionRecordingId="session-expired"
                pendingSeek={null}
                unavailable={<span>Recording gone</span>}
            />
        )
        expect(getByText('Recording gone')).toBeTruthy()
        expect(mockPlayer).not.toHaveBeenCalled()
    })
})
