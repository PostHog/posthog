import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { mockLargeScoutFleet, mockScoutConfigs, mockScoutCosts, mockScoutRuns } from '../../../__mocks__/scoutConfigs'
import { ScoutsRoster } from './ScoutsRoster'

// The roster: one column of scout cards under the search, filter, and sort toolbar. Use this to
// check the card layout, the status dots, the run strips, and how a wide fleet reads.

const meta: Meta<typeof ScoutsRoster> = {
    title: 'Scenes-App/Inbox/ScoutsRoster',
    component: ScoutsRoster,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        featureFlags: { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true },
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/runs/findings/summary/': () => [200, null],
                '/api/projects/:id/signals/scout/metadata/current/': () => [200, null],
                '/api/projects/:id/signals/scout/scratchpad/': () => [200, []],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ScoutsRoster>

export const Roster: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, mockScoutConfigs],
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, mockScoutRuns(mockScoutConfigs)],
            },
        }),
    ],
}

export const LargeFleet: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, mockLargeScoutFleet],
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [
                    200,
                    mockScoutRuns(mockLargeScoutFleet),
                ],
            },
        }),
    ],
}

// Cost, staff only. The fleet mixes the three cases: a scout that spent and filed reports, one that
// spent and filed nothing, and one whose runs had no spend attributed and so shows no numbers.
const COST_MOCKS = mswDecorator({
    get: {
        '/api/projects/:id/signals/scout/configs/': () => [200, mockLargeScoutFleet],
        '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, mockScoutRuns(mockLargeScoutFleet)],
        '/api/projects/:id/signals/scout/runs/costs/': () => [200, mockScoutCosts(mockLargeScoutFleet)],
    },
})

export const RosterCosts: Story = {
    decorators: [COST_MOCKS],
}

// The same fleet for a non-staff reader: no cost line on any card, and no request for one.
export const RosterCostsNonStaff: Story = {
    decorators: [
        COST_MOCKS,
        mswDecorator({
            get: { '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, is_staff: false }] },
        }),
    ],
}
