import { render, screen } from '@testing-library/react'

import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { RecordingUnavailable } from './RecordingUnavailable'

describe('recording unavailable fallback', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings/:id': () => [404, { detail: 'Recording not found' }],
            },
        })
        initKeaTests()
    })

    it('replaces the generic replay 404, which would send the user to check capture settings', async () => {
        render(
            <SessionRecordingPlayer
                sessionRecordingId="sess-gone"
                playerKey="test"
                mode={SessionRecordingPlayerMode.Standard}
                autoPlay={false}
                notFoundContent={<RecordingUnavailable sessionId="sess-gone" />}
            />
        )

        expect(await screen.findByText(/This recording is no longer available/)).toBeTruthy()
        expect(screen.queryByText(/Session replay is enabled for this project/)).toBeNull()
        expect(screen.queryByText(/Session replay is disabled for this project/)).toBeNull()
    })
})
