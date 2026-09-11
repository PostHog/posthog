import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AgentsRoster } from './AgentsRoster'

const SUPPORT_ROW_OFF = /^Support is off in project settings/

function supportRow(): HTMLElement {
    return screen.getByLabelText('Expand Support').parentElement as HTMLElement
}

describe('AgentsRoster', () => {
    let enablementCalls: Record<string, unknown>[] = []

    const mountRoster = async (projectAdmin: boolean): Promise<void> => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {})
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            conversations_enabled: false,
            effective_membership_level: projectAdmin
                ? OrganizationMembershipLevel.Admin
                : OrganizationMembershipLevel.Member,
        })
        render(<AgentsRoster />)
        await waitFor(() => expect(screen.getByText('Support')).toBeInTheDocument())
    }

    beforeEach(() => {
        initKeaTests()
        enablementCalls = []
        // msw handlers reset between tests, so register per test rather than once per file.
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [200, { results: [] }],
                '/api/projects/:team_id/vision/scanners/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
                '/api/projects/:team_id/event_definitions/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    { count: 0, next: null, previous: null, results: [] },
                ],
            },
            post: {
                '/api/projects/:team_id/product_enablement/': async ({ request }) => {
                    enablementCalls.push((await request.clone().json()) as Record<string, unknown>)
                    return [200, { results: { conversations: 'enabled' } }]
                },
            },
        })
    })
    afterEach(cleanup)

    it('enables the backing setting from the collapsed row', async () => {
        await mountRoster(true)

        await userEvent.click(within(supportRow()).getByText('Turn on'))

        await waitFor(() => expect(enablementCalls).toEqual([{ products: ['conversations'] }]))
    })

    it('names the setting and the admin requirement instead of the row', async () => {
        await mountRoster(false)

        expect(screen.getByText('Admin needed')).toBeInTheDocument()
        expect(within(supportRow()).getByText('Turn on').closest('button')).toHaveAttribute('aria-disabled', 'true')
        await userEvent.click(screen.getByLabelText('Expand Support'))
        expect(screen.getByText(SUPPORT_ROW_OFF)).toHaveTextContent('Only project admins can turn it on.')
    })
})
