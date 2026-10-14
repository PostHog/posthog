import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { render, screen } from '@testing-library/react'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { ScoutTrials } from './ScoutTrials'

jest.mock('./ScoutTrialsPanel', () => ({
    ScoutTrialsPanel: ({ configId }: { configId?: string }) => <div>Trial editor for {configId ?? 'all scouts'}</div>,
}))

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

const mockGetAccessControlDisabledReason = getAccessControlDisabledReason as jest.MockedFunction<
    typeof getAccessControlDisabledReason
>

describe('ScoutTrials access', () => {
    test.each<[number, boolean, boolean, string | undefined, 'editor' | 'staff' | 'skill_access']>([
        [2, true, true, undefined, 'editor'],
        [2, true, true, 'scout-1', 'editor'],
        [2, true, false, 'scout-1', 'skill_access'],
        [2, false, true, 'scout-1', 'staff'],
        [3, true, true, 'scout-1', 'staff'],
    ])('team %s with staff=%s, skill editor=%s and scout=%s shows %s', (teamId, isStaff, isEditor, configId, shown) => {
        initKeaTests(false)
        mockGetAccessControlDisabledReason.mockReturnValue(isEditor ? null : 'Editor access is required.')
        const unmountTeam = teamLogic.mount()
        const unmountUser = userLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: teamId })
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })

        const view = render(<ScoutTrials configId={configId} />)
        expect(screen.queryByText(`Trial editor for ${configId ?? 'all scouts'}`) !== null).toBe(shown === 'editor')
        expect(screen.queryByText('Scout trials are available to staff in the internal project.') !== null).toBe(
            shown === 'staff'
        )
        expect(screen.queryByText(/Scout trials need editor access to skills/) !== null).toBe(shown === 'skill_access')

        view.unmount()
        unmountUser()
        unmountTeam()
    })
})
