import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    allReports,
    mockArtefacts,
    mockReviewers,
    mockSignals,
    mockSourceConfigs,
    mockTask,
    mockTeamConfig,
    pullRequestReports,
} from './__mocks__/inboxMocks'
import { mockLargeScoutFleet, mockScoutConfigs, mockScoutRuns } from './__mocks__/scoutConfigs'
import { InboxScene } from './InboxScene'
import { INBOX_LAST_UI_STATE_STORAGE_KEY } from './logics/inboxOnboardingLogic'

// Full Inbox scene with a populated report list. Use this to polish the holistic
// layout: header, page tabs, the Reports view switcher, scope picker, filter bar, and the
// centered list column. Switch tabs / views / scope inside the story to exercise each.

// The scene reads its tab, view, and open surface from the URL.
function routeTo(pathname: string, searchParams: Record<string, string> = {}): Decorator {
    return (Story) => {
        useEffect(() => {
            router.actions.push(pathname, searchParams)
        }, [])
        return <Story />
    }
}

const sceneMocks = mswDecorator({
    get: {
        '/api/projects/:id/signals/reports': () => [
            200,
            { results: allReports, count: allReports.length, next: null, previous: null },
        ],
        '/api/projects/:id/signals/reports/available_reviewers': () => [200, mockReviewers],
        '/api/projects/:id/signals/reports/:reportId': (req) => {
            const report = allReports.find((candidate) => candidate.id === req.params.reportId)
            return report ? [200, report] : [404, { detail: 'Not found.' }]
        },
        '/api/projects/:id/signals/reports/:reportId/artefacts': (req) => [
            200,
            mockArtefacts(req.params.reportId as string),
        ],
        '/api/projects/:id/signals/reports/:reportId/signals': (req) => [
            200,
            { report: null, signals: mockSignals(req.params.reportId as string, 4) },
        ],
        '/api/projects/:id/tasks/:taskId': (req) => [200, mockTask(req.params.taskId as string)],
        '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
        '/api/projects/:id/signals/config': () => [200, mockTeamConfig],
        '/api/projects/:id/signals/scout/configs': () => [200, []],
        '/api/projects/:id/signals/scout/runs': () => [200, []],
        '/api/projects/:id/signals/scout/runs/recent-per-scout': () => [200, []],
        '/api/projects/:id/external_data_sources': () => [200, { results: [], count: 0 }],
        '/api/projects/:id/external_data_sources/': () => [200, { results: [], count: 0 }],
    },
})

const meta: Meta = {
    title: 'Scenes-App/Inbox/Scene',
    component: InboxScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        featureFlags: {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            [FEATURE_FLAGS.INBOX_SELF_DRIVING_EMPTY_STATE]: 'empty-state',
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        },
        // The scene shell keeps a loader element mounted past the VR wait window, so don't block on it.
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [sceneMocks],
}
export default meta

type Story = StoryObj

export const Inbox: Story = {}

// Triage mode over the Needs-a-decision queue: one report at a time, keyboard-driven.
export const Triage: Story = {
    decorators: [routeTo(urls.inboxTriage())],
}

export const Scouts: Story = {
    decorators: [
        routeTo(urls.inbox('scouts')),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs': () => [200, mockScoutConfigs],
                '/api/projects/:id/signals/scout/runs/recent-per-scout': () => [200, mockScoutRuns(mockScoutConfigs)],
            },
        }),
    ],
}

export const Settings: Story = {
    decorators: [routeTo(urls.inbox('settings'))],
}

// The layout the flag replaces: one tab per report list, the Runs and Configuration tabs, and the
// setup rail. Story parameters replace the meta's, so the meta-level flags are re-listed.
const LEGACY_FLAGS = {
    [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
    [FEATURE_FLAGS.INBOX_SELF_DRIVING_EMPTY_STATE]: 'empty-state',
    [FEATURE_FLAGS.INBOX_REDESIGN]: false,
}

export const Legacy: Story = {
    parameters: { featureFlags: LEGACY_FLAGS },
    decorators: [routeTo(urls.inbox('pulls'))],
}

export const LegacyReport: Story = {
    parameters: { featureFlags: LEGACY_FLAGS },
    decorators: [routeTo(urls.inboxReport('pulls', pullRequestReports[0].id))],
}

export const LegacyScouts: Story = {
    parameters: { featureFlags: LEGACY_FLAGS },
    decorators: [
        routeTo(urls.inbox('scouts')),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/scout/configs': () => [200, mockScoutConfigs],
                '/api/projects/:id/signals/scout/runs/recent-per-scout': () => [200, mockScoutRuns(mockScoutConfigs)],
            },
        }),
    ],
}

// Set up (sources enabled) but no reports yet – exercises the empty list states.
export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
                '/api/projects/:id/signals/scout/configs': () => [200, mockScoutConfigs],
            },
        }),
    ],
}

export const EmptyControl: Story = {
    parameters: {
        featureFlags: {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            [FEATURE_FLAGS.INBOX_SELF_DRIVING_EMPTY_STATE]: 'control',
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
                '/api/projects/:id/signals/scout/configs': () => [200, mockScoutConfigs],
            },
        }),
    ],
}

export const EmptyWithManyScouts: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
                '/api/projects/:id/signals/scout/configs': () => [200, mockLargeScoutFleet],
            },
        }),
    ],
}

export const InstallingSelfDriving: Story = {
    decorators: [
        (Story) => {
            useMountedLogic(wizardActiveSessionDetectorLogic)
            useEffect(() => {
                wizardActiveSessionDetectorLogic.actions.markActive(SELF_DRIVING_WORKFLOW_ID)
                return () => wizardActiveSessionDetectorLogic.actions.markInactive()
            }, [])
            return <Story />
        },
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
            },
        }),
    ],
}

// Fresh project: nothing watching and nothing in the inbox → the single-command takeover.
export const SelfDrivingOnboarding: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
            },
        }),
    ],
}

// The same fresh-project state with the welcome-redesign experiment's test arm pinned → the
// full-pane hero welcome (no tab row) instead of the locked "Welcome" tab.
export const SelfDrivingOnboardingRedesign: Story = {
    parameters: {
        // Story parameters replace the meta's, so the meta-level flag is re-listed here.
        featureFlags: {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            [FEATURE_FLAGS.INBOX_WELCOME_REDESIGN]: 'test',
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
            },
        }),
    ],
}

// First-ever visit while the set-up verdict is still loading (config + count requests hang, no
// cached verdict) → the neutral skeleton, with no tab bar and no welcome page. Guards the
// regression where the normal tabbed inbox rendered first and was then swapped for the takeover.
export const SelfDrivingVerdictPending: Story = {
    decorators: [
        (StoryFn) => {
            // Other stories cache their settled verdict; this story is the no-history first visit.
            window.localStorage.removeItem(INBOX_LAST_UI_STATE_STORAGE_KEY)
            return <StoryFn />
        },
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => new Promise(() => {}),
                '/api/projects/:id/signals/source_configs': () => new Promise(() => {}),
                '/api/projects/:id/signals/scout/configs': () => new Promise(() => {}),
            },
        }),
    ],
}

// Had self-driving before (reports exist) but nothing is watching now → the sleek re-enable banner
// over the normal inbox, so existing work stays accessible. Reports are mocked explicitly (not
// inherited) so "existing work" is unambiguous and the banner – not the takeover – is shown.
export const SelfDrivingPaused: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [
                    200,
                    { results: allReports, count: allReports.length, next: null, previous: null },
                ],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
            },
        }),
    ],
}
