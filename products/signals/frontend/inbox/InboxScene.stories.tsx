import type { Decorator, Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

import {
    allReports,
    mockArtefacts,
    mockReviewers,
    mockSignals,
    mockSourceConfigs,
    mockSourceMetadata,
    mockTask,
    mockTeamConfig,
    reportTabReports,
} from './__mocks__/inboxMocks'
import { mockLargeScoutFleet, mockScoutConfigs, mockScoutRuns, mockScoutSuggestionSet } from './__mocks__/scoutConfigs'
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
        '/api/projects/:id/integrations/github/available_installations/': {
            discovery_id: '11111111-1111-4111-8111-111111111111',
            discovered_at: '2026-06-11T00:00:00Z',
            installations: [],
            personal_github_connected: false,
            personal_github_login: null,
            personal_discovery_status: 'not_connected',
        },
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
        // Must precede the `:taskId` handler, which would otherwise swallow this path.
        '/api/projects/:id/tasks/repo_routing_rules/': () => [200, []],
        '/api/projects/:id/tasks/:taskId': (req) => [200, mockTask(req.params.taskId as string)],
        '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
        '/api/projects/:id/signals/config': () => [200, mockTeamConfig],
        '/api/projects/:id/signals/scout/configs': () => [200, []],
        '/api/projects/:id/signals/scout/runs': () => [200, []],
        '/api/projects/:id/signals/scout/runs/recent-per-scout': () => [200, []],
        '/api/projects/:id/external_data_sources': () => [200, { results: [], count: 0 }],
        '/api/projects/:id/external_data_sources/': () => [200, { results: [], count: 0 }],
    },
    post: {
        '/api/projects/:id/signals/reports/source_metadata/': mockSourceMetadata(allReports),
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
            [FEATURE_FLAGS.SIGNALS_REPORT_METRICS]: true,
        },
        // The scene shell keeps a loader element mounted past the VR wait window, so don't block on it.
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [sceneMocks],
}
export default meta

type Story = StoryObj

export const Inbox: Story = {}

const valueSummaryMocks = mswDecorator({
    get: {
        '/api/projects/:team_id/signals/inbox_summary/': {
            period_start: '2026-06-04T00:00:00Z',
            period_end: '2026-06-11T00:00:00Z',
            merged_pr_count: 12,
            people_count: 5,
            participation_complete: true,
            pull_requests: Array.from({ length: 12 }, (_, index) => ({
                repository: index % 3 === 0 ? 'PostHog/posthog-js' : 'PostHog/posthog',
                number: 111094 - index,
                url: `https://github.com/${index % 3 === 0 ? 'PostHog/posthog-js' : 'PostHog/posthog'}/pull/${111094 - index}`,
            })),
            people: [
                { id: 1, login: 'sam-example' },
                { id: 2, login: 'alex-example' },
                { id: 3, login: 'riley-example' },
                { id: 4, login: 'taylor-example' },
                { id: 5, login: 'jordan-example' },
            ],
        },
    },
})

export const ReportsNarrow: Story = {
    parameters: {
        featureFlags: {
            ...meta.parameters?.featureFlags,
            [FEATURE_FLAGS.INBOX_TIME_WINDOW]: true,
            [FEATURE_FLAGS.INBOX_SOURCE_FILTER]: true,
        },
        testOptions: { viewport: { width: 390, height: 844 }, waitForLoadersToDisappear: false },
    },
    play: async ({ canvas }) => {
        await userEvent.click(await canvas.findByLabelText('Filters'))
        // The panel renders in a popover outside the story root, and fades in after the click.
        await waitFor(() => expect(within(document.body).getByText('Reset to default')).toBeVisible())
    },
}

export const WithValueSummary: Story = {
    parameters: {
        featureFlags: {
            ...meta.parameters?.featureFlags,
            [FEATURE_FLAGS.SIGNALS_INBOX_VALUE_SUMMARY]: true,
        },
    },
    decorators: [valueSummaryMocks],
}

function reportWithEvidenceItems(count: number): Story {
    return {
        decorators: [
            routeTo(urls.inboxReport('reports', reportTabReports[0].id)),
            mswDecorator({
                get: {
                    '/api/projects/:id/signals/reports/:reportId/signals': (req) => [
                        200,
                        { report: null, signals: mockSignals(req.params.reportId as string, count) },
                    ],
                },
            }),
        ],
    }
}

export const ReportWithManyEvidenceItems: Story = reportWithEvidenceItems(12)
export const ReportWithTwoEvidenceItems: Story = reportWithEvidenceItems(2)
export const ReportWithoutEvidence: Story = reportWithEvidenceItems(0)

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

const findingsRuns = [
    {
        run_id: 'findings-run-errors',
        skill_name: 'signals-scout-error-tracking',
        emitted_count: 2,
        emitted_finding_ids: ['checkout-500s', 'invite-null-email'],
        emitted_report_ids: [],
        created_at: '2026-06-10T18:00:00Z',
    },
    {
        run_id: 'findings-run-replay',
        skill_name: 'signals-scout-session-replay',
        emitted_count: 1,
        emitted_finding_ids: ['rage-clicks-billing'],
        emitted_report_ids: [reportTabReports[0].id],
        created_at: '2026-06-10T12:00:00Z',
    },
].map((run) => ({
    ...run,
    total_spend: null,
    skill_version: 1,
    status: 'completed' as const,
    started_at: run.created_at,
    completed_at: run.created_at,
    task_url: null,
    summary: 'Filed what changed since the last run.',
    edited_report_ids: [],
    metadata: {},
}))

const findingsEmissions = [
    {
        id: 'emission-checkout-500s',
        run_id: 'findings-run-errors',
        finding_id: 'checkout-500s',
        description: 'A new TypeError on the checkout page started at 14:00 and now affects about one in ten sessions.',
        severity: 'P1' as const,
        tags: ['new-error', 'checkout'],
        source_id: 'run:findings-run-errors:finding:checkout-500s',
        emitted_at: '2026-06-10T18:10:00Z',
    },
    {
        id: 'emission-invite-null-email',
        run_id: 'findings-run-errors',
        finding_id: 'invite-null-email',
        description: 'Team invites with an empty recipient row raise a 500 instead of a validation error.',
        severity: 'P2' as const,
        tags: ['regression'],
        source_id: 'run:findings-run-errors:finding:invite-null-email',
        emitted_at: '2026-06-10T18:08:00Z',
    },
    {
        id: 'emission-rage-clicks-billing',
        run_id: 'findings-run-replay',
        finding_id: 'rage-clicks-billing',
        description: 'People rage-click the disabled upgrade button on the billing page before they leave.',
        severity: 'P3' as const,
        tags: ['usability'],
        source_id: 'run:findings-run-replay:finding:rage-clicks-billing',
        emitted_at: '2026-06-10T12:12:00Z',
    },
]

function findingsMocks(emissionsFail = false): Decorator {
    return mswDecorator({
        get: {
            '/api/projects/:id/signals/scout/configs': () => [200, mockScoutConfigs],
            '/api/projects/:id/signals/scout/runs': () => [200, findingsRuns],
            '/api/projects/:id/signals/scout/runs/findings/summary/': () => [200, null],
            '/api/projects/:id/signals/scout/metadata/current/': () => [200, null],
            '/api/projects/:id/signals/scout/scratchpad/': () => [200, []],
            '/api/projects/:id/signals/scout/suggestions/': () => [200, mockScoutSuggestionSet()],
            '/api/projects/:id/vision/scanners/': { count: 0, next: null, previous: null, results: [] },
        },
        post: {
            '/api/projects/:id/signals/scout/configs/sync/': () => [200, mockScoutConfigs],
            '/api/projects/:id/signals/scout/runs/emissions/batch/': () =>
                emissionsFail ? [500, { detail: 'Server error' }] : [200, findingsEmissions],
            '/api/projects/:id/signals/scout/runs/emissions/reports/batch/': () => [
                200,
                [
                    {
                        finding_id: 'invite-null-email',
                        source_id: 'run:findings-run-errors:finding:invite-null-email',
                        report: { id: reportTabReports[0].id, title: reportTabReports[0].title, status: 'ready' },
                    },
                ],
            ],
        },
    })
}

export const ScoutFindings: Story = {
    decorators: [routeTo(urls.inboxFindings()), findingsMocks()],
    play: async ({ canvas }) => {
        await expect(canvas.findByText(/rage-click the disabled upgrade button/)).resolves.toBeVisible()
    },
}

export const ScoutFindingsLoadFailed: Story = {
    decorators: [routeTo(urls.inboxFindings()), findingsMocks(true)],
    play: async ({ canvas }) => {
        await expect(canvas.findByText(/Couldn't load signals/)).resolves.toBeVisible()
    },
}

export const Settings: Story = {
    decorators: [routeTo(urls.inbox('settings'))],
}

export const Sources: Story = {
    decorators: [routeTo(urls.inbox('sources'))],
    parameters: { testOptions: { snapshotBrowsers: [] } },
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

// Fresh project: nothing watching and nothing in the inbox → the full-pane welcome page (no tab row).
export const SelfDrivingOnboarding: Story = {
    name: 'Welcome page with GitHub and manual setup',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
                '/api/projects/:id/signals/onboarding/': { draft: null, completed_at: null },
            },
            post: {
                '/api/projects/:id/signals/onboarding/expose/': { draft: null, completed_at: null },
            },
        }),
    ],
}

export const GuidedOnboardingComplete: Story = {
    decorators: [
        ...(Array.isArray(Empty.decorators) ? Empty.decorators : []),
        mswDecorator({
            get: {
                '/api/projects/:id/signals/onboarding/': {
                    draft: {
                        step: 'github',
                        sources: [],
                        scanner_ids: [],
                        suggestions: [],

                        automatic_implementation: false,
                        implementation_priority: 'P1',
                    },
                    completed_at: '2026-06-11T10:00:00Z',
                },
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

// Had self-driving before (reports exist) but nothing is watching now and the in-app setup never
// completed → the sleek re-enable banner over the normal inbox, so existing work stays accessible.
// Reports are mocked explicitly (not inherited) so "existing work" is unambiguous and the banner –
// not the takeover – is shown.
export const SelfDrivingPaused: Story = {
    play: async ({ canvas }) => {
        await expect(canvas.findByText('Self-driving is paused')).resolves.toBeVisible()
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [
                    200,
                    { results: allReports, count: allReports.length, next: null, previous: null },
                ],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
                '/api/projects/:id/signals/onboarding/': { draft: null, completed_at: null },
            },
        }),
    ],
}
