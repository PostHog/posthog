import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AfterClickingCard } from './AfterClickingCard'
import { emailImpactLogic } from './emailImpactLogic'

describe('AfterClickingCard', () => {
    beforeEach(() => {
        useMocks({
            get: { '/api/projects/:team_id/transactional_email_log/impact/': () => [200, null] },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    test.each([
        { replay: false, shown: true },
        { replay: true, shown: false },
    ])('shows the card only while session replay is off (replay on: $replay)', ({ replay, shown }) => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, session_recording_opt_in: replay })

        render(
            <BindLogic logic={emailImpactLogic} props={{ workflowId: 'workflow-1' }}>
                <AfterClickingCard />
            </BindLogic>
        )

        expect(screen.queryByText('What people did after clicking') !== null).toBe(shown)
    })
})
