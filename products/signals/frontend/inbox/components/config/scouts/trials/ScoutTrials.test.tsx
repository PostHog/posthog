import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { ScoutTrials } from './ScoutTrials'

jest.mock('./ScoutTrialsPanel', () => ({
    ScoutTrialsPanel: ({ configId }: { configId?: string }) => <div>Trial editor for {configId ?? 'all scouts'}</div>,
}))

describe('ScoutTrials access', () => {
    test.each<[number, boolean, string | undefined, boolean]>([
        [2, true, undefined, true],
        [2, true, 'scout-1', true],
        [2, false, 'scout-1', false],
        [3, true, 'scout-1', false],
    ])('team %s with staff=%s and scout=%s can open editor=%s', (teamId, isStaff, configId, allowed) => {
        initKeaTests(false)
        const unmountTeam = teamLogic.mount()
        const unmountUser = userLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: teamId })
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })

        const view = render(<ScoutTrials configId={configId} />)
        expect(screen.queryByText(`Trial editor for ${configId ?? 'all scouts'}`) !== null).toBe(allowed)
        expect(screen.queryByText('Scout trials are available to staff in the internal project.') !== null).toBe(
            !allowed
        )

        view.unmount()
        unmountUser()
        unmountTeam()
    })
})
