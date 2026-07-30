import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { ObservationStatsApi, ReplayScannerApi, UserBasicApi, VisionQuotaApi } from '../generated/api.schemas'

const alice: UserBasicApi = {
    id: 1,
    uuid: '00000000-0000-0000-0000-000000000001',
    first_name: 'Alice',
    last_name: 'Anderson',
    email: 'alice@example.com',
    hedgehog_config: null,
}
const bob: UserBasicApi = {
    id: 2,
    uuid: '00000000-0000-0000-0000-000000000002',
    first_name: 'Bob',
    last_name: 'Brown',
    email: 'bob@example.com',
    hedgehog_config: null,
}

const scanner = (overrides: Partial<ReplayScannerApi> = {}): ReplayScannerApi =>
    ({
        id: '00000000-0000-0000-0000-00000000000a',
        name: 'Scanner',
        description: '',
        scanner_type: 'monitor',
        scanner_config: { prompt: 'Did the user struggle?' },
        query: null,
        sampling_rate: 1,
        provider: 'google',
        model: 'gemini-3.6-flash',
        enabled: true,
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: '2026-05-12T00:00:00Z',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        created_by: null,
        credits_this_month: 0,
        ...overrides,
    }) as ReplayScannerApi

const scanners = {
    count: 4,
    next: null,
    previous: null,
    results: [
        scanner({
            id: '00000000-0000-0000-0000-00000000000a',
            name: 'Confused checkout',
            credits_this_month: 1250,
            description: 'Flags sessions where the user hesitated at payment.',
            scanner_type: 'monitor',
            sampling_rate: 1,
            created_by: alice,
        }),
        scanner({
            id: '00000000-0000-0000-0000-00000000000b',
            name: 'Frustration tags',
            credits_this_month: 0,
            scanner_type: 'classifier',
            scanner_config: { prompt: 'Tag this session.', tags: ['rage-click', 'dead-end'], multi_label: true },
            enabled: false,
            sampling_rate: 0.25,
            created_by: bob,
        }),
        scanner({
            id: '00000000-0000-0000-0000-00000000000c',
            name: 'Session summary',
            credits_this_month: 5,
            scanner_type: 'summarizer',
            scanner_config: { prompt: 'Summarize this session.', length: 'medium' },
            sampling_rate: 0.05,
            created_by: alice,
        }),
        scanner({
            id: '00000000-0000-0000-0000-00000000000d',
            name: 'Intent score',
            credits_this_month: 320,
            scanner_type: 'scorer',
            scanner_config: { prompt: 'Score this session.', scale: { min: 0, max: 10 } },
            sampling_rate: 1,
            created_by: null,
        }),
    ],
}

const quota: VisionQuotaApi = {
    credit_limit: 10000,
    credits_used: 2400,
    remaining: 7600,
    exhausted: false,
    projected_monthly_credits: 5200,
    period_start: '2026-05-01T00:00:00Z',
    period_end: '2026-06-01T00:00:00Z',
}

const summarizerScanner = scanners.results[2]

const summarizerStats: ObservationStatsApi = {
    status_counts: { total: 148, succeeded: 142, failed: 4, ineligible: 2, in_flight: 0, success_rate: 0.97 },
    coverage: { recent_sessions: 142, total_sessions: 1840, recent_days: 14 },
    labels: { up_total: 0, down_total: 0, by_day: [], by_rating_day: [], version_markers: [] },
    available_tags: [],
    monitor: null,
    classifier: null,
    scorer: null,
    summarizer: {
        friction_ranked: [
            { term: 'checkout stalls after applying a coupon', count: 21 },
            { term: 'search returns no results for valid skus', count: 14 },
            { term: 'filter selection resets on back navigation', count: 9 },
            { term: 'payment form rejects valid card numbers', count: 6 },
            { term: 'session times out mid-signup', count: 3 },
        ],
        keyword_ranked: [
            { term: 'checkout', count: 68 },
            { term: 'coupon', count: 41 },
            { term: 'abandoned', count: 33 },
            { term: 'search', count: 27 },
            { term: 'signup', count: 12 },
        ],
        total_with_facets: 138,
        total_with_friction: 53,
    },
} as ObservationStatsApi

// A daily observation volume so the chart has something to draw above the panels.
const trendDays = [
    '2026-04-29',
    '2026-04-30',
    '2026-05-01',
    '2026-05-02',
    '2026-05-03',
    '2026-05-04',
    '2026-05-05',
    '2026-05-06',
    '2026-05-07',
    '2026-05-08',
    '2026-05-09',
    '2026-05-10',
    '2026-05-11',
    '2026-05-12',
]
const observationsTrend = {
    results: [
        {
            action: { id: '$recording_observed', type: 'events', order: 0, name: '$recording_observed' },
            label: 'Observations',
            count: 142,
            data: [8, 11, 9, 14, 10, 12, 7, 13, 9, 11, 10, 8, 12, 8],
            labels: trendDays,
            days: trendDays,
        },
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Replay Vision',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-12',
        pageUrl: urls.replayVision(),
        featureFlags: [FEATURE_FLAGS.REPLAY_VISION],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/': scanners,
                '/api/projects/:team_id/vision/quota/': quota,
            },
        }),
    ],
}
export default meta

export const ScannersList: StoryObj = {}

// Nothing else renders the summarizer's friction/keyword panels, so this story is what catches regressions there.
export const SummarizerOverview: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(summarizerScanner.id),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/:id/': summarizerScanner,
                '/api/projects/:team_id/vision/scanners/:id/observations/': {
                    count: 0,
                    next: null,
                    previous: null,
                    results: [],
                },
                '/api/projects/:team_id/vision/scanners/:id/observations/stats/': summarizerStats,
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': observationsTrend,
            },
        }),
    ],
}
