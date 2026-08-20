import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { mockLargeScoutFleet, mockScoutConfigs } from '../../../__mocks__/scoutConfigs'
import { ScoutsRoster } from './ScoutsRoster'

// The flat roster: one alphabetical table with a sortable Status column. Use this to check the
// column layout, the status dots, and how a wide fleet reads without lifecycle sections.

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
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, []],
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
            },
        }),
    ],
}

export const LargeFleet: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs/': () => [200, mockLargeScoutFleet],
            },
        }),
    ],
}
