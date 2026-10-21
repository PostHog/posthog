import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { HomeTab } from './HomeTab'

jest.mock('./HomeTabDefault', () => ({
    HomeTabDefault: () => <div>PostHog Home</div>,
}))
jest.mock('scenes/dashboard/Dashboard', () => ({
    Dashboard: ({ id }: { id: string }) => <div>Home dashboard {id}</div>,
}))

describe('HomeTab', () => {
    afterEach(cleanup)

    it.each([
        ['the opinionated Home dashboard', null, 'PostHog Home'],
        ['a selected Home dashboard', 42, 'Home dashboard 42'],
    ])('renders %s', (_scenario, existingDashboardId, expectedContent) => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            home_tab_dashboard: existingDashboardId,
        })

        render(<HomeTab />)
        expect(screen.getByText(expectedContent)).toBeInTheDocument()
    })

    it('keeps the selected dashboard visible while team data refreshes', () => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            home_tab_dashboard: 42,
        })
        teamLogic.actions.loadCurrentTeam()
        expect(teamLogic.values.currentTeamLoading).toBe(true)

        render(<HomeTab />)

        expect(screen.getByText('Home dashboard 42')).toBeInTheDocument()
        expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })

    it('shows the initial loading state before a team is available', () => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess(null)
        teamLogic.actions.loadCurrentTeam()

        render(<HomeTab />)

        expect(screen.getByLabelText('Loading product analytics Home')).toBeInTheDocument()
        expect(screen.queryByText('PostHog Home')).not.toBeInTheDocument()
    })
})
