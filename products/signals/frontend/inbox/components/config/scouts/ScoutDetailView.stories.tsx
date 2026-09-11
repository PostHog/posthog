import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { mockScoutConfigs, mockScoutCosts, mockScoutRuns } from '../../../__mocks__/scoutConfigs'
import { ScoutDetailView } from './ScoutDetailView'

// One scout's page. Use this to check the stat strip, including the staff-only cost tiles and the
// spend line under it.

const SKILL_NAME = mockScoutConfigs[0].skill_name

const meta: Meta<typeof ScoutDetailView> = {
    title: 'Scenes-App/Inbox/ScoutDetailView',
    component: ScoutDetailView,
    args: { skillName: SKILL_NAME },
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
                '/api/projects/:id/signals/scout/configs/': () => [200, mockScoutConfigs],
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, mockScoutRuns(mockScoutConfigs)],
                '/api/projects/:id/signals/scout/runs/costs/': () => [200, mockScoutCosts(mockScoutConfigs)],
                '/api/projects/:id/signals/scout/runs/findings/summary/': () => [200, null],
                '/api/projects/:id/signals/scout/metadata/current/': () => [200, null],
                '/api/projects/:id/signals/scout/scratchpad/': () => [200, []],
                '/api/projects/:id/signals/scout/notes/': () => [200, []],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof ScoutDetailView>

export const ScoutPage: Story = {}

// The same scout for a non-staff reader: no cost tiles, no spend line, and no request for either.
export const ScoutPageNonStaff: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, is_staff: false }] },
        }),
    ],
}

// A scout that spent but filed nothing: the third tile says so rather than pricing zero reports.
export const ScoutPageNoReports: Story = {
    args: { skillName: mockScoutConfigs[1].skill_name },
}
