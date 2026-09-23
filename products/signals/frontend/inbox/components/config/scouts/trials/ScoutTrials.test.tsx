import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { ScoutTrials } from './ScoutTrials'

jest.mock('./ScoutTrialsPanel', () => ({ ScoutTrialsPanel: () => <div>Comparison editor</div> }))

describe('ScoutTrials access', () => {
    test.each([
        [2, true, true],
        [2, false, false],
        [3, true, false],
    ])('team %s with staff=%s can open editor=%s', (teamId, isStaff, allowed) => {
        initKeaTests(false)
        const unmountTeam = teamLogic.mount()
        const unmountUser = userLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: teamId })
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })

        const view = render(<ScoutTrials />)
        expect(screen.queryByText('Comparison editor') !== null).toBe(allowed)
        expect(screen.queryByText('Scout comparisons are available to staff in the internal project.') !== null).toBe(
            !allowed
        )

        view.unmount()
        unmountUser()
        unmountTeam()
    })
})
