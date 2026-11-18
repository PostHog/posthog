import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { cleanup, render } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { mockScoutConfigs } from '../../../__mocks__/scoutConfigs'
import { ScoutRubricsButton } from './ScoutRubricsButton'

describe('ScoutRubricsButton', () => {
    beforeEach(() => {
        initKeaTests()
        userLogic.mount()
    })

    afterEach(() => {
        cleanup()
        userLogic.unmount()
    })

    it.each([
        [2, true, true],
        [2, false, false],
        [3, true, false],
    ])('limits the rubric editor to internal staff in team 2 (team %s, staff %s)', (teamId, isStaff, visible) => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: teamId })
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })

        const { queryByText } = render(<ScoutRubricsButton config={mockScoutConfigs[0]} />)

        expect(queryByText('Rubrics') !== null).toBe(visible)
    })
})
