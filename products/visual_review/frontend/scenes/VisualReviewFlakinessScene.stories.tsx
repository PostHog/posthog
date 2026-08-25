import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'

import { mswDecorator } from '~/mocks/browser'

import type { FlakinessEntryApi, FlakinessOverviewApi, RepoApi } from '../generated/api.schemas'

const REPO_ID = '00000000-0000-0000-0000-0000000000bb'

const repo: RepoApi = {
    id: REPO_ID,
    team_id: 1,
    repo_external_id: 99999,
    repo_full_name: 'PostHog/posthog',
    baseline_file_paths: {},
    enable_pr_comments: true,
    created_at: '2026-06-10T00:00:00Z',
}

// Dense, sparse and silent 30-day series, so the strip renders all three shapes.
function series(pattern: 'chronic' | 'burst' | 'silent'): number[] {
    return Array.from({ length: 30 }, (_, day) => {
        if (pattern === 'silent') {
            return 0
        }
        if (pattern === 'burst') {
            // Two variants after the baseline moved on day 25, nothing before it.
            return day === 27 || day === 29 ? 1 : 0
        }
        return day % 3 === 0 ? 2 : day % 3 === 1 ? 1 : 0
    })
}

const entry = (overrides: Partial<FlakinessEntryApi>): FlakinessEntryApi => ({
    identifier: 'components-hogcharts-piechart--donut--dark',
    run_type: 'storybook',
    browser: null,
    thumbnail_hash: null,
    width: 320,
    height: 200,
    variant_count: 41,
    last_flaked_at: '2026-06-10T09:00:00Z',
    avg_diff_percentage: 0.041,
    baseline_age_days: 34,
    daily_variant_counts: series('chronic'),
    baseline_moved_day_index: null,
    flakiness_state: 'unstable',
    is_quarantined: false,
    needs_decision: false,
    quarantine: null,
    ...overrides,
})

const overview: FlakinessOverviewApi = {
    entries: [
        entry({}),
        entry({
            identifier: 'components-playerinspector-itemevent--default--dark',
            variant_count: 33,
            avg_diff_percentage: 0.112,
            baseline_age_days: 61,
            is_quarantined: true,
            needs_decision: true,
            quarantine: {
                id: '00000000-0000-0000-0000-0000000000c1',
                reason: 'Non-deterministic rendering (animations, timestamps)',
                expires_at: '2026-06-07T00:00:00Z',
                created_at: '2026-05-08T00:00:00Z',
                created_by: { id: 1, first_name: 'Julian', email: 'julian@posthog.com' },
                source_run: null,
            },
        }),
        entry({
            identifier: 'charts-heatmap--linear-color-scale--light',
            variant_count: 2,
            avg_diff_percentage: 0.021,
            baseline_age_days: 4,
            daily_variant_counts: series('burst'),
            baseline_moved_day_index: 25,
            last_flaked_at: '2026-06-09T09:00:00Z',
        }),
    ],
    totals: {
        listed: 3,
        tracked: 4494,
        unstable: 231,
        settled: 604,
        quarantined: 47,
        needs_decision: 12,
        by_run_type: { storybook: 3 },
    },
    truncated: false,
    generated_at: '2026-06-10T10:00:00Z',
}

const emptyOverview: FlakinessOverviewApi = {
    entries: [],
    totals: {
        listed: 0,
        tracked: 4494,
        unstable: 0,
        settled: 0,
        quarantined: 0,
        needs_decision: 0,
        by_run_type: {},
    },
    truncated: false,
    generated_at: '2026-06-10T10:00:00Z',
}

const emptyList = { count: 0, next: null, previous: null, results: [] }

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Visual review/Flakiness',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-10',
        pageUrl: `/visual_review/repos/${REPO_ID}/flakiness`,
        testOptions: { waitForSelector: '[data-attr="visual-review-flakiness-preset-unstable"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/visual_review/repos/${REPO_ID}/`]: repo,
                [`/api/projects/:team_id/visual_review/repos/${REPO_ID}/flakiness/`]: overview,
                [`/api/projects/:team_id/visual_review/repos/${REPO_ID}/quarantine/`]: emptyList,
                '/api/projects/:team_id/visual_review/repos/': { ...emptyList, count: 1, results: [repo] },
            },
        }),
    ],
}
export default meta

// Chronic drip, a quarantine that has run out while the snapshot still flakes,
// and a burst against a four-day-old baseline.
export const Unstable: StoryObj = {}

// A repo whose snapshots all render deterministically. Two of the three repos in
// this project land here, so it is worth holding to the same standard.
export const NothingToShow: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/visual_review/repos/${REPO_ID}/flakiness/`]: emptyOverview,
            },
        }),
    ],
}

// A failed load has to look different from an empty repo. Both leave the scene
// with no overview, and rendering NothingToShow here would claim every snapshot
// is stable on the strength of a request that never answered.
export const CouldNotLoad: StoryObj = {
    // The stat tiles are hidden on this screen, so the meta-level selector never
    // appears and the snapshot would wait for it forever.
    parameters: { testOptions: { waitForSelector: '[data-attr="visual-review-flakiness-retry"]' } },
    decorators: [
        mswDecorator({
            get: {
                [`/api/projects/:team_id/visual_review/repos/${REPO_ID}/flakiness/`]: [
                    500,
                    { detail: 'Upstream timed out' },
                ],
            },
        }),
    ],
}
