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

const SCANNERS = Array.from({ length: 10 }, (_, index) => ({
    id: `scanner-${index}`,
    name: `Scanner ${index}`,
    description: `Watches step ${index}.`,
    scanner_type: 'monitor',
    enabled: true,
    emits_signals: false,
}))

const EMPTY_LIST = { count: 0, next: null, previous: null, results: [] }

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
                    { count: SCANNERS.length, next: null, previous: null, results: SCANNERS },
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
        // The roster only loads its sources behind this flag, so without it every list stays empty.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
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

    // The cap keeps a long user-created list from burying the sources below it, but a filter that
    // could not reach past it would make a scanner unfindable by name.
    it('caps the scanner list, and lets both the filter and Show more reach past the cap', async () => {
        render(<AgentsRoster />)
        await userEvent.click(await screen.findByText('Replay vision'))

        expect(await screen.findByText('Scanner 7')).toBeInTheDocument()
        expect(screen.queryByText('Scanner 8')).not.toBeInTheDocument()

        await userEvent.type(screen.getByPlaceholderText('Filter scanners'), 'Scanner 9')
        expect(await screen.findByText('Scanner 9')).toBeInTheDocument()

        await userEvent.clear(screen.getByPlaceholderText('Filter scanners'))
        await userEvent.click(await screen.findByText('Show 2 more scanners'))
        expect(await screen.findByText('Scanner 9')).toBeInTheDocument()
    })
})
