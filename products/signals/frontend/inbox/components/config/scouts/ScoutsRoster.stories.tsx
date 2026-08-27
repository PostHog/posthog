import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { mockLargeScoutFleet, mockScoutConfigs, mockScoutRuns } from '../../../__mocks__/scoutConfigs'
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

// Phone width with the flag off. Cadence and Next run drop out, and the table stops overflowing
// sideways, so the name, the status, the run strip, and the on/off toggle all stay on screen.
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
