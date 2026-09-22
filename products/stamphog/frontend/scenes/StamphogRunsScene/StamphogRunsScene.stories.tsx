import type { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { ReviewRunApi, StamphogRepoConfigApi } from '../../generated/api.schemas'

const repoConfigs = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: '00000000-0000-0000-0000-0000000000a1',
            repository: 'PostHog/posthog',
            provider: 'github',
            enabled: true,
            digest_enabled: true,
            installation_id: '1',
            review_mode: 'all',
            trigger_label: 'stamphog',
            created_at: '2026-07-01T00:00:00Z',
            updated_at: '2026-07-01T00:00:00Z',
        },
        {
            id: '00000000-0000-0000-0000-0000000000a2',
            repository: 'PostHog/hogland',
            provider: 'github',
            enabled: true,
            digest_enabled: false,
            installation_id: '2',
            review_mode: 'label',
            trigger_label: 'stamphog',
            created_at: '2026-07-01T00:00:00Z',
            updated_at: '2026-07-01T00:00:00Z',
        },
    ] as StamphogRepoConfigApi[],
}

const run = (overrides: Partial<ReviewRunApi>): ReviewRunApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000b0',
        pull_request: '00000000-0000-0000-0000-0000000000c0',
        repository: 'PostHog/posthog',
        pr_number: 83812,
        pr_url: 'https://github.com/PostHog/posthog/pull/83812',
        title: 'fix(cdp): stop double-encoding hog function inputs',
        author_login: 'posthog[bot]',
        head_sha: 'a91f3cd8e2b1447fa0c2d9e5b7318fa4c02d1e77',
        head_branch: 'fix/hog-inputs-encoding',
        delivery_id: '7d2a91e0-9b44-11f0-8f31-2c1a4b6d90ff',
        trigger: 'self_driving',
        status: 'completed',
        verdict: 'approved',
        gate_result: { gate_blocked: false, final_verdict: 'APPROVED' },
        output: { stamphog_version: '2.0.0b4', reviewer_exit_code: 0 },
        error: '',
        posted_review_id: 2884991204,
        verdict_posted_at: '2026-08-17T14:05:52Z',
        approval_dismissed_at: null,
        created_at: '2026-08-17T14:02:11Z',
        updated_at: '2026-08-17T14:05:52Z',
        completed_at: '2026-08-17T14:05:52Z',
        ...overrides,
    }) as ReviewRunApi

const reviewRuns = {
    count: 6,
    next: null,
    previous: null,
    results: [
        run({}),
        run({
            id: '00000000-0000-0000-0000-0000000000b1',
            pr_number: 83809,
            title: 'feat(warehouse): add incremental sync cursor overrides',
            head_sha: 'c02b17a4e9d8331fb7245c8a1e60d3b9f4a7c112',
            status: 'gated',
            verdict: 'refused',
            gate_result: { gate_blocked: true, final_verdict: 'REFUSED' },
            output: { stamphog_version: '2.0.0b4' },
            posted_review_id: null,
            verdict_posted_at: '2026-08-17T13:47:13Z',
            created_at: '2026-08-17T13:47:02Z',
            completed_at: '2026-08-17T13:47:13Z',
        } as Partial<ReviewRunApi>),
        run({
            id: '00000000-0000-0000-0000-0000000000b2',
            repository: 'PostHog/hogland',
            pr_number: 402,
            pr_url: 'https://github.com/PostHog/hogland/pull/402',
            title: 'chore(deps): bump temporalio to 1.9.0',
            author_login: 'webjunkie',
            head_sha: '4fe8b2077c1a9e3d5b06f8241ac93de70b115f6a',
            trigger: 'label',
            status: 'failed',
            verdict: 'error',
            gate_result: {},
            output: { reviewer_exit_code: 124 },
            error: 'Reviewer exited with code 124: sandbox command timed out after 1500s',
            posted_review_id: null,
            verdict_posted_at: null,
            created_at: '2026-08-17T13:31:44Z',
            completed_at: '2026-08-17T13:56:47Z',
        } as Partial<ReviewRunApi>),
        run({
            id: '00000000-0000-0000-0000-0000000000b3',
            pr_number: 83801,
            title: 'fix(insights): guard empty series in trend export',
            head_sha: '8ba0e4192f7c6ab35d0e17c9f4a82b6d503e1a99',
            // The supersede paths stamp the status and updated_at but leave completed_at null, so this
            // row is what proves a terminal run's duration stops instead of growing against now.
            status: 'superseded',
            verdict: 'none',
            gate_result: {},
            output: {},
            posted_review_id: null,
            verdict_posted_at: null,
            created_at: '2026-08-17T13:12:08Z',
            updated_at: '2026-08-17T13:12:50Z',
            completed_at: null,
        } as Partial<ReviewRunApi>),
        run({
            id: '00000000-0000-0000-0000-0000000000b4',
            pr_number: 83790,
            title: 'chore(devex): split oversized reviewer module',
            head_sha: '1d40b9c8a2e74f13c95b0da6e28f7143b6c09e55',
            status: 'reviewing',
            verdict: 'none',
            gate_result: {},
            output: {},
            posted_review_id: null,
            verdict_posted_at: null,
            created_at: '2026-08-17T12:44:19Z',
            completed_at: null,
        } as Partial<ReviewRunApi>),
        run({
            id: '00000000-0000-0000-0000-0000000000b5',
            pr_number: 83781,
            title: 'feat(flags): local evaluation payload v2',
            head_sha: '70ab3f1d6e28c4590b7fa1362d84e0c7195bf3a2',
            verdict: 'escalate',
            gate_result: { gate_blocked: false, final_verdict: 'ESCALATE' },
            posted_review_id: null,
            created_at: '2026-08-17T12:20:55Z',
            completed_at: '2026-08-17T12:26:07Z',
        } as Partial<ReviewRunApi>),
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Stamphog/Runs',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-17 23:30:00',
        pageUrl: urls.stamphogRuns(),
        testOptions: { waitForSelector: '[data-attr="stamphog-runs-trigger-filter"]' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/review_runs/': reviewRuns,
                '/api/projects/:team_id/stamphog/repo_configs/': repoConfigs,
            },
        }),
    ],
}
export default meta

// Every lifecycle state stamphog can leave behind: approved, gate-blocked, failed, superseded,
// still reviewing, and escalated to a human.
export const RunsList: StoryObj = {}

export const RunsListEmpty: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/stamphog/review_runs/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
            },
        }),
    ],
}
