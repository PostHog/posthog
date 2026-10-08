import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import { mockDailyQuietRuns, mockScoutConfigs, mockScoutCosts, mockScoutRuns } from '../../../__mocks__/scoutConfigs'
import { inboxSceneLogic } from '../../../inboxSceneLogic'
import { ScoutDetailView } from './ScoutDetailView'
import { trialFixtureConfig } from './trials/scoutTrialsFixtures'
import { createScoutTrialsStoryMocks } from './trials/scoutTrialsStoryMocks'

// One scout's page. Use this to check the health strip, including the staff-only cost segment, and
// the Reports / Runs / Signals tabs below it.

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

// The same scout for a non-staff reader: no cost segment, and no request for one.
export const ScoutPageNonStaff: Story = {
    decorators: [
        mswDecorator({
            get: { '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, is_staff: false }] },
        }),
    ],
}

// A scout that spent but filed nothing: no reports segment, and Runs leads the tabs.
export const ScoutPageNoReports: Story = {
    args: { skillName: mockScoutConfigs[1].skill_name },
}

// The folded run group at its widest, in the narrowest pane it has to survive: runs a day apart
// carry the long date form at both ends of the group header, which has to wrap rather than clip.
export const ScoutPageNarrowRunHistory: Story = {
    args: { skillName: mockScoutConfigs[1].skill_name },
    parameters: { testOptions: { viewport: { width: 375, height: 900 }, waitForLoadersToDisappear: false } },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [
                    200,
                    mockDailyQuietRuns(mockScoutConfigs[1]),
                ],
            },
        }),
    ],
}

const trialsMocks = createScoutTrialsStoryMocks()
const trialsDecorators: Decorator[] = [
    (Story) => {
        useMountedLogic(inboxSceneLogic)
        useEffect(() => {
            teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 2 })
            userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 42, is_staff: true })
            router.actions.replace(urls.inboxScout(trialFixtureConfig.skill_name), { tab: 'trials' })
        }, [])
        return <Story />
    },
    mswDecorator({
        ...trialsMocks.mocks,
        get: {
            ...trialsMocks.mocks.get,
            '/api/projects/:id/signals/scout/configs/': () => [200, [trialFixtureConfig]],
            '/api/projects/:id/signals/scout/runs/recent-per-scout/': () => [200, []],
            '/api/projects/:id/signals/scout/runs/costs/': () => [200, mockScoutCosts([trialFixtureConfig])],
        },
    }),
]

export const ScoutPageTrials: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY, FEATURE_FLAGS.INBOX_REDESIGN, FEATURE_FLAGS.SCOUT_TRIALS],
    },
    args: { skillName: trialFixtureConfig.skill_name },
    decorators: [
        ...trialsDecorators,
        (Story) => (
            <div className="flex h-screen w-full">
                <Story />
            </div>
        ),
    ],
}

export const ScoutPageTrialsNarrow: Story = {
    parameters: {
        featureFlags: [FEATURE_FLAGS.PRODUCT_AUTONOMY, FEATURE_FLAGS.INBOX_REDESIGN, FEATURE_FLAGS.SCOUT_TRIALS],
    },
    args: { skillName: trialFixtureConfig.skill_name },
    decorators: [
        ...trialsDecorators,
        (Story) => (
            // A docked side panel leaves about 520px for this scene on a laptop.
            <div className="flex h-screen w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
