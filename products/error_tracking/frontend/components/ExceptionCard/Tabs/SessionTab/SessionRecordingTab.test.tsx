import { render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventProperties } from 'lib/components/Errors/types'

import { initKeaTests } from '~/test/init'

import { SessionRecordingContent } from './SessionRecordingTab'

const SESSION_ID = '0199aaaa-bbbb-cccc-dddd-eeeeffff0000'

// What the existence lookup has answered for this session, read fresh on every render.
const mockRecordingExists: { value: boolean | undefined } = { value: undefined }

jest.mock('scenes/session-recordings/player/SessionRecordingPlayer', () => ({
    SessionRecordingPlayer: () => <div data-attr="session-recording-player" />,
}))

jest.mock('lib/components/ViewRecordingButton/sessionRecordingInfoLogic', () => {
    const kea = jest.requireActual('kea')
    return {
        sessionRecordingInfoLogic: kea.kea([
            kea.path(['test', 'sessionRecordingInfoLogicStub']),
            kea.actions({ checkRecordingInfo: (sessionId: string) => ({ sessionId }) }),
            kea.selectors({ getRecordingExists: [() => [], () => () => mockRecordingExists.value] }),
        ]),
    }
})

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

function renderTab(recordingStatus?: string): HTMLElement {
    const properties = {
        $session_id: SESSION_ID,
        $recording_status: recordingStatus,
    } as unknown as ErrorEventProperties

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
        mockRecordingExists.value = undefined
    })

    it('explains the miss on the event instead of mounting a player that can only 404', () => {
        mockRecordingExists.value = false
        const container = renderTab('disabled')

        expect(container.textContent).toContain('Replay was not active when capturing this event')
        expect(playerIn(container)).toBeNull()
    })

    it('falls back to the plain miss when the recorder reported no status', () => {
        mockRecordingExists.value = false
        const container = renderTab(undefined)

        expect(container.textContent).toContain('No recording for this event')
        expect(playerIn(container)).toBeNull()
    })

    // Loading, empty and error are three different screens — an unanswered lookup is not "empty",
    // and an inactive recorder status alone must not retire the player.
    it('keeps the player while the existence lookup has not answered', () => {
        mockRecordingExists.value = undefined
        const container = renderTab('disabled')

        expect(playerIn(container)).not.toBeNull()
    })

    it('keeps the player when a recording is known to exist', () => {
        mockRecordingExists.value = true
        const container = renderTab('disabled')

        expect(playerIn(container)).not.toBeNull()
    })
})
