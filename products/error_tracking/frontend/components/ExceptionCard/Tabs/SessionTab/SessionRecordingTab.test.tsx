import { render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventProperties } from 'lib/components/Errors/types'

import { initKeaTests } from '~/test/init'

import { SessionRecordingContent } from './SessionRecordingTab'

jest.mock('scenes/session-recordings/player/SessionRecordingPlayer', () => ({
    SessionRecordingPlayer: () => <div data-attr="session-recording-player" />,
}))

// The real logic connects to the recording data coordinator, which mounts the whole playback
// pipeline. The tab only reads four settled values from it, so a static stand-in is enough.
jest.mock('./sessionTabLogic', () => {
    const kea = jest.requireActual('kea')
    // `jest.mock` factories are hoisted above module scope, so the id is inlined here.
    const sessionId = '0199aaaa-bbbb-cccc-dddd-eeeeffff0000'
    return {
        sessionTabLogic: kea.kea([
            kea.path(['test', 'sessionTabLogicStub']),
            kea.reducers({
                recordingProps: [{ playerKey: 'session-tab', sessionRecordingId: sessionId }, {}],
                recordingTimestamp: [null, {}],
                isTimestampOutsideRecording: [false, {}],
                sessionId: [sessionId, {}],
            }),
        ]),
    }
})

const SESSION_ID = '0199aaaa-bbbb-cccc-dddd-eeeeffff0000'

function renderTab(properties: ErrorEventProperties): HTMLElement {
    const { container } = render(
        <Provider>
            <BindLogic logic={errorPropertiesLogic} props={{ id: 'exception-uuid', properties }}>
                <SessionRecordingContent />
            </BindLogic>
        </Provider>
    )
    return container
}

const playerIn = (container: HTMLElement): Element | null =>
    container.querySelector('[data-attr="session-recording-player"]')

describe('SessionRecordingContent', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('explains the miss on the event instead of mounting a player that can only 404', () => {
        const container = renderTab({
            $session_id: SESSION_ID,
            $recording_status: 'disabled',
            $has_recording: false,
        } as unknown as ErrorEventProperties)

        expect(container.textContent).toContain('Replay was not active when capturing this event')
        expect(playerIn(container)).toBeNull()
    })

    it('mounts the player when the recorder was running', () => {
        const container = renderTab({
            $session_id: SESSION_ID,
            $recording_status: 'active',
        } as unknown as ErrorEventProperties)

        expect(playerIn(container)).not.toBeNull()
    })

    // A recorder that reports itself off can still sit in a session recorded earlier.
    it('keeps the player when a recording is known to exist', () => {
        const container = renderTab({
            $session_id: SESSION_ID,
            $recording_status: 'disabled',
            $has_recording: true,
        } as unknown as ErrorEventProperties)

        expect(playerIn(container)).not.toBeNull()
    })
})
