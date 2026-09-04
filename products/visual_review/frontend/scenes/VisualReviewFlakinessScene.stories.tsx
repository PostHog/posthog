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
            // Two runs after the baseline moved on day 25, nothing before it.
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
    hard_count: 4,
    soft_count: 26,
    window_runs: 770,
    hard_rate: 4 / 770,
    soft_rate: 26 / 770,
    last_flaked_at: '2026-06-10T09:00:00Z',
    avg_diff_percentage: 0.041,
    worst_soft_diff_percentage: 0.31,
    headroom: (2.5 - 0.31) / 2.5,
    baseline_age_days: 34,
    daily_hard_counts: series('burst'),
    daily_soft_counts: series('chronic'),
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
            // A quarantine still doing its job: the snapshot fails nearly every
            // run, so nothing about it has gone clean and nobody has to answer.
            identifier: 'components-playerinspector-itemevent--default--dark',
            variant_count: 0,
            hard_count: 764,
            soft_count: 0,
            hard_rate: 764 / 770,
            soft_rate: 0,
            worst_soft_diff_percentage: null,
            headroom: null,
            avg_diff_percentage: null,
            baseline_age_days: 61,
            daily_hard_counts: series('chronic'),
            daily_soft_counts: series('silent'),
            flakiness_state: 'broken',
            is_quarantined: true,
            needs_decision: false,
            quarantine: {
                id: '00000000-0000-0000-0000-0000000000c1',
                reason: 'Non-deterministic rendering (animations, timestamps)',
                source: 'human',
                expires_at: '2026-06-07T00:00:00Z',
                created_at: '2026-05-08T00:00:00Z',
                created_by: { id: 1, first_name: 'Julian', email: 'julian@posthog.com' },
                source_run: null,
            },
        }),
        entry({
            // Absorbed on every run, but its worst diff is a rounding error
            // away from the threshold, so it is one restyle from turning red.
            identifier: 'charts-heatmap--linear-color-scale--light',
            variant_count: 2,
            hard_count: 0,
            soft_count: 705,
            hard_rate: 0,
            soft_rate: 705 / 770,
            avg_diff_percentage: 2.19,
            worst_soft_diff_percentage: 2.42,
            headroom: (2.5 - 2.42) / 2.5,
            baseline_age_days: 4,
            daily_hard_counts: series('silent'),
            daily_soft_counts: series('burst'),
            baseline_moved_day_index: 25,
            flakiness_state: 'at_risk',
            last_flaked_at: '2026-06-09T09:00:00Z',
        }),
    ],
    totals: {
        listed: 3,
        tracked: 4494,
        broken: 18,
        unstable: 231,
        at_risk: 63,
        noisy: 604,
        clean: 812,
        quarantined: 47,
        // Zero, and deliberately so: none of the three entries needs a decision,
        // and a total that disagreed with them would send the landing logic to a
        // preset with nothing to render.
        needs_decision: 0,
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
        broken: 0,
        unstable: 0,
        at_risk: 0,
        noisy: 0,
        clean: 0,
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
export const Unstable: StoryObj = {
    // Names its own preset. Inheriting the default made this story a hostage to
    // it: the default changed, no fixture matched the new one, and the story
    // quietly rendered an empty table for a while before anybody noticed.
    parameters: { pageUrl: `/visual_review/repos/${REPO_ID}/flakiness#preset=unstable` },
}

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
