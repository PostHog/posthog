import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { DashboardType } from '~/types'

import { toolStreamEventsLogic } from 'products/posthog_ai/frontend/api/logics'

import { HomeTab } from './HomeTab'
import { homeTabDashboardProps } from './homeTabDashboardLogic'

jest.mock('./HomeTabDefault', () => ({
    HomeTabDefault: () => <div>PostHog Home</div>,
}))
jest.mock('scenes/dashboard/Dashboard', () => ({
    Dashboard: ({
        id,
        placement,
        readOnly,
        headerActions,
    }: {
        id: string
        placement: string
        readOnly?: boolean
        headerActions?: JSX.Element
    }) => (
        <>
            <div>Home dashboard {id}</div>
            <div>{`placement: ${placement}, read-only: ${!!readOnly}`}</div>
            {headerActions}
        </>
    ),
}))

const PAGE = { title: <div>Page title</div>, dashboardHeaderActions: <div>Customize menu</div> }

describe('HomeTab', () => {
    afterEach(cleanup)

    it.each([
        ['the opinionated Home dashboard', null, undefined, ['PostHog Home']],
        [
            'a selected dashboard inside the Insights tab',
            42,
            undefined,
            ['Home dashboard 42', 'placement: builtin, read-only: true'],
        ],
        [
            'a selected dashboard as the whole page, with its own header',
            42,
            PAGE,
            ['Home dashboard 42', 'placement: dashboard, read-only: false', 'Customize menu'],
        ],
    ])('renders %s', (_scenario, existingDashboardId, page, expectedContents) => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            home_tab_dashboard: existingDashboardId,
        })

        render(<HomeTab page={page} />)
        for (const expectedContent of expectedContents) {
            expect(screen.getByText(expectedContent)).toBeInTheDocument()
        }
        expect(screen.queryByText('Page title')).not.toBeInTheDocument()
    })

    it.each([
        ['offers a way back when the selected dashboard has no charts', [], false, 'This dashboard has no charts yet'],
        ['shows the selected dashboard when it has charts', [{ id: 1, deleted: false }], false, 'Home dashboard 42'],
        [
            'keeps the dashboard error and retry when a reload of an empty dashboard fails',
            [],
            true,
            'Home dashboard 42',
        ],
    ])('%s', (_scenario, tiles, reloadFails, expectedContent) => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            home_tab_dashboard: 42,
        })
        render(<HomeTab />)

        act(() => {
            dashboardLogic(homeTabDashboardProps(42)).actions.loadDashboardSuccess({
                id: 42,
                tiles,
            } as unknown as DashboardType)
            if (reloadFails) {
                dashboardLogic(homeTabDashboardProps(42)).actions.loadDashboardFailure('Network error')
            }
        })

        expect(screen.getByText(expectedContent)).toBeInTheDocument()
    })

    it('keeps the same AI listener when the first chart replaces the empty state', () => {
        initKeaTests()
        toolStreamEventsLogic.mount()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            home_tab_dashboard: 42,
        })
        render(<HomeTab page={PAGE} />)
        const loadDashboard = (tiles: unknown[]): void =>
            act(() => {
                dashboardLogic(homeTabDashboardProps(42, 'page')).actions.loadDashboardSuccess({
                    id: 42,
                    tiles,
                    user_access_level: 'editor',
                } as unknown as DashboardType)
            })

        loadDashboard([])
        const listenersOnEmptyDashboard = Object.keys(toolStreamEventsLogic.values.toolListeners)
        loadDashboard([{ id: 1, deleted: false }])

        expect(screen.getByText('Home dashboard 42')).toBeInTheDocument()
        expect(listenersOnEmptyDashboard).toHaveLength(1)
        expect(Object.keys(toolStreamEventsLogic.values.toolListeners)).toEqual(listenersOnEmptyDashboard)
    })

    it('falls back to PostHog Home and reloads the team when the selected dashboard is gone', () => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            home_tab_dashboard: 42,
        })
        render(<HomeTab />)

        act(() => {
            dashboardLogic(homeTabDashboardProps(42)).actions.dashboardNotFound()
        })

        expect(screen.getByText('PostHog Home')).toBeInTheDocument()
        expect(teamLogic.values.currentTeamLoading).toBe(true)
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
