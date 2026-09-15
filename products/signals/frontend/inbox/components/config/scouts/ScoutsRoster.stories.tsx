import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { mockLargeScoutFleet, mockScoutConfigs, mockScoutCosts, mockScoutRuns } from '../../../__mocks__/scoutConfigs'
import { ScoutsRoster } from './ScoutsRoster'
import { ScoutsRosterLegacy } from './ScoutsRosterLegacy'

// The roster: one column of scout cards under the search, filter, and sort toolbar. Use this to
// check the card layout, the status dots, the run strips, and how a wide fleet reads.

const meta: Meta<typeof ScoutsRoster> = {
    title: 'Scenes-App/Inbox/ScoutsRoster',
    component: ScoutsRoster,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        featureFlags: { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true, [FEATURE_FLAGS.INBOX_REDESIGN]: true },
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

// The table roster with the redesign flag off. Story parameters replace the meta's, so the
// meta-level flag is re-listed.
const LEGACY_FLAGS = { [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true, [FEATURE_FLAGS.INBOX_REDESIGN]: false }

export const RosterLegacy: Story = {
    parameters: { featureFlags: LEGACY_FLAGS },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, mockScoutConfigs],
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, mockScoutRuns(mockScoutConfigs)],
            },
        }),
    ],
    render: () => <ScoutsRosterLegacy />,
}

// Phone width with the flag off. Owners, Cadence, and Next run drop out, and the table stops
// overflowing sideways, so the name, the status, the run strip, and the on/off toggle all stay on
// screen.
export const Narrow: Story = {
    parameters: {
        featureFlags: LEGACY_FLAGS,
        testOptions: { viewport: { width: 375, height: 900 }, waitForLoadersToDisappear: false },
    },
    render: () => <ScoutsRosterLegacy />,
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

// The table roster with the cost columns: `$/day`, `$/run`, and `$/report` before the run strip.
export const RosterCostsTable: Story = {
    parameters: { featureFlags: LEGACY_FLAGS },
    render: () => <ScoutsRosterLegacy />,
    decorators: [COST_MOCKS],
}
