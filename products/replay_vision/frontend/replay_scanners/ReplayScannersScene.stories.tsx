import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'
import { RecordingsQuery } from '~/queries/schema/schema-general'
import { StartupProgramLabel } from '~/types'

import type {
    BackfillEstimateResponseApi,
    DraftScannerResponseApi,
    ObservationStatsApi,
    ReplayObservationApi,
    ReplayScannerApi,
    ReplayScannerBackfillApi,
    ReplayScannerPromptSuggestionApi,
    ScannerSelfDrivingStatsApi,
    ScannerStatsResponseApi,
    UserBasicApi,
    VisionQuotaApi,
} from '../generated/api.schemas'
import { replayScannerLogic } from './replayScannerLogic'
import type { SamplingMode, ScannerConfig, ScannerType } from './types'

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
        tags: [],
        scanner_type: 'monitor',
        scanner_config: { prompt: 'Did the user struggle?' },
        query: null,
        sampling_rate: 1,
        // The API always serializes this (non-null column with a default), so a fixture without it
        // would render the editor's form default instead of the scanner's own coverage.
        sampling_mode: 'comprehensive',
        provider: 'google',
        model: 'gemini-3.8-flash',
        enabled: true,
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: '2026-05-12T00:00:00Z',
        created_at: '2026-05-12T00:00:00Z',
        updated_at: '2026-05-12T00:00:00Z',
        created_by: null,
        credits_this_month: 0,
        observations_this_month: 0,
        credits_per_observation: 1,
        estimated_monthly_observations: null,
        estimated_monthly_credits: null,
        estimated_at: null,
        user_access_level: 'editor',
        sweep_throttle_factor: 1,
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
            observations_this_month: 1250,
            estimated_monthly_observations: 3100,
            estimated_monthly_credits: 3100,
            estimated_at: '2026-05-10T00:00:00Z',
            description: 'Flags sessions where the user hesitated at payment.',
            tags: ['checkout', 'core flows'],
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
            observations_this_month: 5,
            estimated_monthly_observations: 40,
            estimated_monthly_credits: 40,
            estimated_at: '2026-05-10T00:00:00Z',
            scanner_type: 'summarizer',
            scanner_config: { prompt: 'Summarize this session.', length: 'medium' },
            sampling_rate: 0.05,
            created_by: alice,
        }),
        scanner({
            id: '00000000-0000-0000-0000-00000000000d',
            name: 'Intent score',
            credits_this_month: 320,
            observations_this_month: 160,
            credits_per_observation: 2,
            estimated_monthly_observations: 1000,
            estimated_monthly_credits: 2000,
            estimated_at: '2026-05-10T00:00:00Z',
            scanner_type: 'scorer',
            scanner_config: { prompt: 'Score this session.', scale: { min: 0, max: 10 } },
            sampling_rate: 1,
            created_by: null,
        }),
    ],
}

const scannerStats: ScannerStatsResponseApi = {
    total: 4,
    enabled: 3,
    by_type: {
        monitor: { enabled: 1, total: 1 },
        classifier: { enabled: 0, total: 1 },
        scorer: { enabled: 1, total: 1 },
        summarizer: { enabled: 1, total: 1 },
    },
}

const quota: VisionQuotaApi = {
    credit_limit: 10000,
    credits_used: 2400,
    remaining: 7600,
    exhausted: false,
    projected_monthly_credits: 5200,
    scanners_monthly_credits: 5200,
    backfills_committed_credits: 0,
    free_monthly_credits: 2500,
    credits_settled: 2400,
    credits_reserved: 0,
    period_start: '2026-05-01T00:00:00Z',
    period_end: '2026-06-01T00:00:00Z',
}

// Settled ledger spend per UTC day of the mocked period, weekends dipping, summing to `quota.credits_used`.
const spendSeries = {
    period_start: quota.period_start,
    period_end: quota.period_end,
    days: [150, 190, 230, 260, 90, 80, 250, 280, 310, 120, 440].map((credits, i) => ({
        date: `2026-05-${String(i + 1).padStart(2, '0')}`,
        credits,
    })),
}

const summarizerScanner = scanners.results[2]

const summarizerStats: ObservationStatsApi = {
    status_counts: { total: 148, succeeded: 142, failed: 4, ineligible: 2, in_flight: 0, success_rate: 0.97 },
    coverage: { recent_sessions: 142, total_sessions: 1840, recent_days: 14 },
    labels: { up_total: 8, down_total: 4, by_day: [], by_rating_day: [], version_markers: [] },
    available_tags: [],
    monitor: null,
    classifier: null,
    scorer: null,
} as ObservationStatsApi

// One finished backfill and one still running, so the history table renders both states.
const backfills: ReplayScannerBackfillApi[] = [
    {
        id: '00000000-0000-0000-0000-0000000000f7',
        status: 'running',
        window_start: '2026-05-05T00:00:00Z',
        window_end: '2026-05-12T00:00:00Z',
        total_count: 420,
        dispatched_count: 260,
        skipped_count: 12,
        credits_per_observation: 1,
        succeeded_count: 231,
        failed_count: 4,
        ineligible_count: 9,
        in_flight_count: 16,
        created_by: alice,
        created_at: '2026-05-11T20:00:00Z',
        finished_at: null,
    },
    {
        id: '00000000-0000-0000-0000-0000000000f8',
        status: 'completed',
        window_start: '2026-04-20T00:00:00Z',
        window_end: '2026-04-27T00:00:00Z',
        total_count: 186,
        dispatched_count: 180,
        skipped_count: 6,
        credits_per_observation: 1,
        succeeded_count: 168,
        failed_count: 2,
        ineligible_count: 4,
        in_flight_count: 0,
        created_by: bob,
        created_at: '2026-04-28T10:00:00Z',
        finished_at: '2026-04-28T11:30:00Z',
    },
] as ReplayScannerBackfillApi[]

const backfillEstimate: BackfillEstimateResponseApi = {
    total_sessions: 312,
    total_credits: 312,
    credits_per_observation: 1,
    credits_remaining: 7600,
    window_start: '2026-05-05T00:00:00Z',
    window_end: '2026-05-12T00:00:00Z',
}

const noSelfDrivingStats: ScannerSelfDrivingStatsApi = {
    signals_emitted: 0,
    reports_contributed: 0,
    prs_opened: 0,
    prs_merged: 0,
    reports: [],
    pull_requests: [],
}

const activeSelfDrivingStats: ScannerSelfDrivingStatsApi = {
    signals_emitted: 64,
    reports_contributed: 9,
    prs_opened: 4,
    prs_merged: 2,
    reports: [
        {
            id: '00000000-0000-0000-0000-0000000000e1',
            title: 'Shipping step stalls after address reset',
            status: 'ready',
        },
        { id: '00000000-0000-0000-0000-0000000000e2', title: 'Coupon field rejects valid codes', status: 'ready' },
    ],
    pull_requests: [
        { url: 'https://github.com/example/shop/pull/412', merged: true },
        { url: 'https://github.com/example/shop/pull/409', merged: true },
        { url: 'https://github.com/example/shop/pull/405', merged: false },
        { url: 'https://github.com/example/shop/pull/398', merged: false },
    ],
}

const monitorOverviewScanner: ReplayScannerApi = {
    ...scanners.results[0],
    scanner_config: {
        prompt: [
            'Did the user struggle to complete checkout?',
            '',
            'Answer yes if the user shows clear friction on the cart, shipping, or payment steps. Friction includes',
            'retrying the payment form, going back to an earlier step, rage-clicking a disabled button, or leaving',
            'the page within a minute of seeing an error message.',
            '',
            'Answer no if the user completes the order without backtracking, or never reaches the cart.',
            '',
            'Ignore sessions from internal staff accounts and sessions shorter than ten seconds.',
        ].join('\n'),
    },
    emits_signals: true,
    credit_limit: 5000,
    credits_used_against_limit: 3400,
    query: {
        kind: 'RecordingsQuery',
        events: [{ id: '$pageview', type: 'events', name: '$pageview', order: 0 }],
        properties: [
            { type: 'recording', key: 'visited_page', value: ['/checkout'], operator: 'icontains' },
            { type: 'person', key: 'plan', value: ['growth'], operator: 'exact' },
        ],
        having_predicates: [{ type: 'recording', key: 'active_seconds', value: 30, operator: 'gt' }],
        filter_test_accounts: true,
    },
    experiment_targeting: { experiment_id: 11, variant: 'test' },
}

const monitorOverviewStats: ObservationStatsApi = {
    ...summarizerStats,
    monitor: { yes_total: 38, no_total: 97, inconclusive_total: 7 },
}

const classifierOverviewScanner: ReplayScannerApi = {
    ...scanners.results[1],
    enabled: true,
    query: {
        kind: 'RecordingsQuery',
        properties: [{ type: 'event', key: '$browser', value: ['Safari'], operator: 'exact' }],
    },
    scanner_config: {
        prompt: 'Tag session.',
        tags: ['rage-click', 'dead-end', 'slow-load', 'form-error'],
        multi_label: true,
        allow_freeform_tags: true,
    },
}

const classifierOverviewStats: ObservationStatsApi = {
    ...summarizerStats,
    available_tags: ['rage-click', 'dead-end', 'slow-load', 'form-error', 'coupon-confusion', 'modal-trap'],
    classifier: {
        fixed_ranked: [
            { tag: 'rage-click', count: 54 },
            { tag: 'slow-load', count: 31 },
            { tag: 'dead-end', count: 18 },
            { tag: 'form-error', count: 9 },
        ],
        freeform_ranked: [
            { tag: 'coupon-confusion', count: 6 },
            { tag: 'modal-trap', count: 2 },
        ],
        total_with_tags: 97,
    },
}

const scorerOverviewScanner: ReplayScannerApi = {
    ...scanners.results[3],
    credit_limit: 400,
    credits_used_against_limit: 399,
    limit_reached: true,
}

const scorerOverviewStats: ObservationStatsApi = {
    ...summarizerStats,
    scorer: {
        summary: { min: 0.5, p25: 3.2, median: 5.1, mean: 5.3, p75: 7.4, max: 9.8, count: 142 },
        histogram: {
            labels: ['0-1', '1-2', '2-3', '3-4', '4-5', '5-6', '6-7', '7-8', '8-9', '9-10'],
            counts: [2, 5, 11, 19, 27, 30, 22, 14, 8, 4],
        },
    },
}

const overviewDecorator = (
    scannerResponse: ReplayScannerApi,
    stats: ObservationStatsApi,
    selfDrivingStats: ScannerSelfDrivingStatsApi = noSelfDrivingStats
): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/vision/scanners/:id/': scannerResponse,
            '/api/projects/:team_id/vision/scanners/:id/observations/stats/': stats,
            '/api/projects/:team_id/vision/scanners/:id/self_driving_stats/': selfDrivingStats,
            '/api/projects/:team_id/experiments/:id/': {
                id: 11,
                name: 'New shipping step',
                feature_flag_key: 'new-shipping-step',
            },
        },
    })

const observation = (overrides: Partial<ReplayObservationApi> = {}): ReplayObservationApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000b1',
        scanner_id: summarizerScanner.id,
        session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d07',
        status: 'succeeded',
        error_reason: '',
        workflow_id: 'vision-observation-1',
        // The API always sends this, and only a configured scanner has a page to link to.
        scanner_origin: 'configured',
        scanner_snapshot: {
            name: summarizerScanner.name,
            scanner_type: 'summarizer',
            scanner_version: 1,
            model: 'gemini-3.8-flash',
            provider: 'google',
            emits_signals: false,
            scanner_config: { prompt: 'Summarize this session.', length: 'medium' },
            verify_positives: 'off',
        },
        scanner_result: {
            model_output: {
                scanner_type: 'summarizer',
                confidence: 0.9,
                title: 'Checkout hesitation after coupon',
                summary:
                    'The user applied a coupon at checkout, hit a validation error twice, and abandoned the cart after retrying payment.',
            },
            signals_count: 0,
        },
        triggered_by: 'schedule',
        triggered_by_user: null,
        distinct_id: 'user_8f3k2j',
        recording_subject_email: 'alice@example.com',
        previous_observation_id: null,
        next_observation_id: null,
        label: null,
        viewed: false,
        started_at: '2026-05-11T09:00:00Z',
        completed_at: '2026-05-11T09:01:00Z',
        created_at: '2026-05-11T09:00:00Z',
        media: [
            {
                id: '00000000-0000-0000-0000-0000000000f1',
                kind: 'thumbnail',
                asset_id: 4001,
                description: null,
                video_start_ms: 24000,
                video_end_ms: null,
            },
        ],
        ...overrides,
    }) as ReplayObservationApi

const observations = {
    count: 4,
    next: null,
    previous: null,
    results: [
        observation(),
        observation({
            id: '00000000-0000-0000-0000-0000000000b2',
            session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d08',
            recording_subject_email: 'very.long.customer.email.address@enterprise-customer-company-name.example.com',
            distinct_id: 'enterprise-user-with-a-very-long-distinct-id-8f3k2j9d2m1x',
            triggered_by: 'on_demand',
            triggered_by_user: alice,
            label: { is_correct: true, feedback: '' },
        }),
        observation({
            id: '00000000-0000-0000-0000-0000000000b3',
            session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d09',
            status: 'failed',
            error_reason: 'provider_transient:The model timed out before returning a result.',
            scanner_result: null,
            recording_subject_email: null,
            distinct_id: null,
            // A scan that never produced a result never rendered a frame either.
            media: [],
        }),
        observation({
            id: '00000000-0000-0000-0000-0000000000b4',
            session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d10',
            recording_subject_email: 'bob@example.com',
            distinct_id: 'user_2m1x9d',
            label: { is_correct: false, feedback: 'Missed the failed payment retry entirely.' },
            viewed: true,
        }),
    ],
}

// Standalone detail-page observation with long unbroken identifiers, prev/next nav, and a rating.
const observationDetail = observation({
    id: '00000000-0000-0000-0000-0000000000d1',
    session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d08',
    recording_subject_email: 'very.long.customer.email.address@enterprise-customer-company-name.example.com',
    distinct_id: 'enterprise-user-with-a-very-long-distinct-id-8f3k2j9d2m1x',
    previous_observation_id: '00000000-0000-0000-0000-0000000000b1',
    next_observation_id: '00000000-0000-0000-0000-0000000000b4',
    label: { is_correct: true, feedback: 'Good catch on the coupon error.' },
    scanner_result: {
        model_output: {
            scanner_type: 'summarizer',
            confidence: 0.87,
            title: 'Coupon validation loop at checkout',
            summary:
                'The user spent most of the session in checkout, retrying an invalid coupon three times before abandoning the cart at the payment step.',
        },
        signals_count: 1,
        verification: null,
    },
})

// Rated wrong with no feedback written yet, the only state where the feedback placeholder shows.
const thumbsDownObservationDetail = observation({
    id: '00000000-0000-0000-0000-0000000000d3',
    session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d12',
    label: { is_correct: false, feedback: '' },
})

// A monitor observation, so the detail page renders the prompt row and the reasoning card that a
// summarizer hides. The prompt is long on purpose: it is what the collapsed row has to clamp.
const monitorObservationDetail = observation({
    id: '00000000-0000-0000-0000-0000000000d2',
    session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d11',
    recording_subject_email: 'bob@example.com',
    distinct_id: 'user_2m1x9d',
    previous_observation_id: '00000000-0000-0000-0000-0000000000b1',
    next_observation_id: '00000000-0000-0000-0000-0000000000b4',
    scanner_snapshot: {
        name: 'Confused checkout',
        scanner_type: 'monitor',
        scanner_version: 3,
        model: 'gemini-3.8-flash',
        provider: 'google',
        emits_signals: true,
        scanner_config: {
            prompt: 'Did the user struggle at checkout? Count it as struggling if they retried a coupon code more than once, resubmitted the payment form after an error, or moved back and forth between the cart and the payment step without completing the order. Ignore sessions that never reached the checkout page at all.',
            allow_inconclusive: true,
        },
        verify_positives: 'off',
    },
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            confidence: 0.82,
            verdict: 'yes',
            reasoning:
                'The user entered a coupon code three times, each time getting a validation error, then switched to the payment form and submitted it twice before leaving the page. That is a retry loop at checkout rather than ordinary browsing.',
        },
        signals_count: 1,
        verification: null,
    },
})

// The pinned strip's default pins, in order: three session columns then a geo event property.
// The values are invented.
const sessionPropertiesRow = ['google.com', 'Paid Search', 'google', 'US']

const promptSuggestion: ReplayScannerPromptSuggestionApi = {
    id: '00000000-0000-0000-0000-0000000000e1',
    status: 'pending',
    suggested_prompt:
        'Summarize this session, calling out any checkout friction: coupon failures, payment retries, or abandoned carts. Keep it under three sentences.',
    base_prompt: 'Summarize this session.',
    base_config: { prompt: 'Summarize this session.', length: 'medium' },
    suggested_config: {
        prompt: 'Summarize this session, calling out any checkout friction: coupon failures, payment retries, or abandoned carts. Keep it under three sentences.',
        length: 'short',
    },
    changes: [
        {
            field: 'prompt',
            kind: 'prompt',
            op: 'set',
            before: 'Summarize this session.',
            after: 'Summarize this session, calling out any checkout friction: coupon failures, payment retries, or abandoned carts. Keep it under three sentences.',
            rationale: 'Thumbs-down ratings cluster on summaries that missed coupon and payment issues.',
        },
        {
            field: 'length',
            kind: 'length',
            op: 'set',
            before: 'medium',
            after: 'short',
            rationale: 'Raters marked longer summaries as less helpful.',
        },
    ],
    rationale:
        'Ratings show summaries skip checkout friction; the rewrite calls it out explicitly and shortens the output.',
    based_on_up: 8,
    based_on_down: 4,
    scanner_version: 1,
    created_at: '2026-05-11T10:00:00Z',
    created_by: alice,
    applied_at: null,
    applied_by: null,
    evaluation: null,
} as ReplayScannerPromptSuggestionApi

const estimate = {
    matched_sessions_in_window: 1840,
    window_days: 30,
    estimated_observations_per_month: 92,
    credits_per_observation: 1,
    estimated_credits_per_month: 92,
    other_enabled_scanners_monthly_credits: 5108,
    sampling_rate: 0.05,
}

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

// Recordings for the on-demand picker, one per status the list can show: a session the scanner
// already observed, one it has not reached, and two the eligibility gate refuses.
const recording = (overrides: Record<string, any>): Record<string, any> => ({
    distinct_id: 'user_8f3k2j',
    viewed: false,
    viewers: [],
    recording_duration: 240,
    active_seconds: 95,
    inactive_seconds: 145,
    start_time: '2026-05-11T09:00:00Z',
    end_time: '2026-05-11T09:04:00Z',
    click_count: 18,
    keypress_count: 9,
    mouse_activity_count: 64,
    console_log_count: 0,
    console_warn_count: 0,
    console_error_count: 0,
    start_url: 'https://app.example.com/checkout',
    person: {
        id: 1001,
        name: 'alice@example.com',
        distinct_ids: ['user_8f3k2j'],
        properties: { email: 'alice@example.com' },
        created_at: '2026-05-01T00:00:00Z',
        uuid: '00000000-0000-0000-0000-0000000000f1',
    },
    snapshot_source: 'web',
    ongoing: false,
    ...overrides,
})

const onDemandRecordings = [
    // Already observed: shares a session id with the succeeded observation above.
    recording({ id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d07' }),
    recording({ id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1e01' }),
    // Over the active-time ceiling, so the scan-time gate would refuse it.
    recording({
        id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1e02',
        recording_duration: 10_800,
        active_seconds: 4_320,
        inactive_seconds: 6_480,
        end_time: '2026-05-11T12:00:00Z',
    }),
    recording({
        id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1e03',
        recording_duration: 9,
        active_seconds: 6,
        inactive_seconds: 3,
        end_time: '2026-05-11T09:00:09Z',
    }),
]

const paginated = (names: string[]): Record<string, any> => ({
    count: names.length,
    next: null,
    previous: null,
    results: names.map((name) => ({ id: name, name, property_type: 'String' })),
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Replay Vision',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-12',
        pageUrl: urls.replayVision(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tags/': ['checkout', 'core flows'],
                '/api/projects/:team_id/vision/scanners/': scanners,
                '/api/projects/:team_id/vision/scanners/stats/': scannerStats,
                '/api/projects/:team_id/vision/scanners/creators/': { creators: [alice, bob] },
                // One card per reason kind, plus one with no cited timestamps (no clip range on the tile).
                '/api/projects/:team_id/vision/scanners/watch_feed/': {
                    results: [
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d1',
                                scanner_id: scanners.results[0].id,
                                scanner_snapshot: {
                                    name: 'Confused checkout',
                                    scanner_type: 'monitor',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: true,
                                    scanner_config: { prompt: 'Did the user hesitate at checkout?' },
                                    verify_positives: 'off',
                                },
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'monitor',
                                        verdict: 'yes',
                                        confidence: 0.92,
                                        reasoning: 'Retried the payment form twice before completing.',
                                        reasoning_segments: [
                                            { kind: 'chip', timestamp_ms: 62000 },
                                            { kind: 'text', value: ' Retried the payment form twice ' },
                                            { kind: 'chip', timestamp_ms: 154000 },
                                        ],
                                    },
                                    signals_count: 2,
                                    verification: null,
                                },
                                viewed: false,
                            }),
                            reason: { kind: 'signal_emitted', signals_count: 2 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d2',
                                scanner_id: scanners.results[3].id,
                                scanner_snapshot: {
                                    name: 'Intent score',
                                    scanner_type: 'scorer',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: false,
                                    scanner_config: { prompt: 'Score this session.', scale: { min: 0, max: 10 } },
                                    verify_positives: 'off',
                                },
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'scorer',
                                        score: 9.5,
                                        confidence: 0.88,
                                        reasoning: 'Compared plans, opened billing, invited a teammate.',
                                        reasoning_segments: [
                                            { kind: 'text', value: 'Compared plans at ' },
                                            { kind: 'chip', timestamp_ms: 30000 },
                                            { kind: 'text', value: ', opened billing, invited a teammate.' },
                                        ],
                                    },
                                    signals_count: 0,
                                    verification: null,
                                },
                                viewed: false,
                            }),
                            reason: { kind: 'outlier_score', score: 9.5, window_mean: 5.1 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d3',
                                recording_subject_email: 'bob@example.com',
                                viewed: true,
                            }),
                            reason: { kind: 'unviewed_recent' },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d4',
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'summarizer',
                                        confidence: 0.8,
                                        title: 'Quick bug report',
                                        summary: 'Hit an error dialog and filed feedback from the toast.',
                                    },
                                    signals_count: 0,
                                    verification: null,
                                },
                                viewed: true,
                            }),
                            reason: { kind: 'recent' },
                        },
                    ],
                },
                '/api/projects/:team_id/vision/quota/': quota,
                '/api/projects/:team_id/vision/quota/spend_series/': spendSeries,
                '/api/projects/:team_id/vision/scanners/:id/': summarizerScanner,
                '/api/projects/:team_id/vision/scanners/:id/self_driving_stats/': noSelfDrivingStats,
                '/api/projects/:team_id/vision/scanners/:id/observations/': observations,
                '/api/projects/:team_id/vision/scanners/:id/observations/stats/': summarizerStats,
                '/api/projects/:team_id/vision/scanners/:scannerId/prompt_suggestions/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [promptSuggestion],
                },
                '/api/projects/:team_id/vision/scanners/:scannerId/prompt_suggestions/current/': {
                    suggestion: promptSuggestion,
                    stale: false,
                    rated_count: 12,
                    evaluation_session_cap: 25,
                },
                '/api/projects/:team_id/vision/observations/:id/': observationDetail,
                // Real bytes, so the poster in the table and on the detail page renders as a reader sees it.
                '/api/projects/:team_id/vision/observations/:id/thumbnail/': () => sessionFrameResponse(),
                '/api/projects/:team_id/vision/scanners/:scannerId/observations/:id/thumbnail/': () =>
                    sessionFrameResponse(),
                '/api/environments/:team_id/session_recordings/': { results: onDemandRecordings, has_next: false },
                '/api/environments/:team_id/session_recordings/matching_events': { results: [] },
                '/api/projects/:team_id/signals/scout/configs/': [],
                '/api/projects/:team_id/signals/scout/runs/recent-per-scout/': [],
                '/api/projects/:team_id/signals/scout/runs/findings/summary/': [],
                '/api/projects/:team_id/signals/scout/metadata/current/': {},
                '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [],
                '/api/projects/:team_id/vision/alerts/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/vision/scanners/:scannerId/backfills/': {
                    count: backfills.length,
                    next: null,
                    previous: null,
                    results: backfills,
                },
                // The three namespaces the pinned-properties picker offers.
                '/api/environments/:team_id/sessions/property_definitions/': paginated([
                    '$entry_referring_domain',
                    '$channel_type',
                    '$entry_utm_source',
                    '$entry_current_url',
                ]),
                '/api/projects/:team_id/property_definitions/': ({ request }) => {
                    const type = new URL(request.url).searchParams.get('type')
                    return type === 'person'
                        ? paginated(['email', 'plan', 'company_size'])
                        : paginated(['$geoip_country_code', '$browser', '$device_type', '$os'])
                },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { query?: string } } | null
                    // The observation page's pinned strip is the only query aliasing its columns this way.
                    return body?.query?.query?.includes('as pinned_0')
                        ? { results: [sessionPropertiesRow] }
                        : observationsTrend
                },
                '/api/projects/:team_id/vision/scanners/estimate/': estimate,
                '/api/projects/:team_id/vision/scanners/:scannerId/backfills/estimate/': backfillEstimate,
            },
        }),
    ],
}
export default meta

export const ScannersList: StoryObj = {}

// A project that has never created a scanner: the surface of the empty-state experiment.
const emptyProjectDecorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/vision/scanners/': { count: 0, next: null, previous: null, results: [] },
            '/api/projects/:team_id/vision/scanners/stats/': {
                total: 0,
                enabled: 0,
                by_type: {
                    monitor: { enabled: 0, total: 0 },
                    classifier: { enabled: 0, total: 0 },
                    scorer: { enabled: 0, total: 0 },
                    summarizer: { enabled: 0, total: 0 },
                },
            } satisfies ScannerStatsResponseApi,
            '/api/projects/:team_id/vision/scanners/creators/': { creators: [] },
        },
    }),
]

export const ScannersListEmpty: StoryObj = {
    decorators: emptyProjectDecorators,
}

export const UsageTab: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision()}?tab=usage` },
}

// The home-redesign experiment's test arm lands on the What to watch feed.
export const HomeWatchFeed: StoryObj = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_HOME_REDESIGN_EXPERIMENT]: 'test' },
    },
}

// A quiet window: nothing scored on any source, so the feed pads to three newest clips and says so
// rather than filling the page with them.
export const HomeWatchFeedOnlyNewest: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/watch_feed/': {
                    results: [0, 1, 2].map((i) => ({
                        observation: observation({ id: `00000000-0000-0000-0000-0000000000f${i}` }),
                        reason: { kind: 'unviewed_recent' },
                    })),
                },
            },
        }),
    ],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_HOME_REDESIGN_EXPERIMENT]: 'test' },
    },
}

export const HomeWatchFeedEmpty: StoryObj = {
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/scanners/watch_feed/': { results: [] } },
        }),
    ],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_HOME_REDESIGN_EXPERIMENT]: 'test' },
    },
}

export const SummarizerOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
}

export const MonitorOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(monitorOverviewScanner.id) },
    decorators: [overviewDecorator(monitorOverviewScanner, monitorOverviewStats, activeSelfDrivingStats)],
}

// Expensive filters stretch the sweep to its hourly ceiling, so the status strip reports it as throttled.
export const ScannerStatusThrottled: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [overviewDecorator({ ...summarizerScanner, sweep_throttle_factor: 12 }, summarizerStats)],
}

export const ClassifierOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(classifierOverviewScanner.id) },
    decorators: [overviewDecorator(classifierOverviewScanner, classifierOverviewStats)],
}

export const ScorerOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(scorerOverviewScanner.id) },
    decorators: [overviewDecorator(scorerOverviewScanner, scorerOverviewStats)],
}

// The scan-drought banner: current version 4 has no marker, and the sweep watermark sits past the
// last config change, so the page warns that the filters matched nothing. No other story renders it.
export const ScannerScanDrought: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/:id/': scanner({
                    id: summarizerScanner.id,
                    name: 'Confused checkout',
                    scanner_type: 'monitor',
                    scanner_config: { prompt: 'Did the user struggle?' },
                    scanner_version: 4,
                    sampling_rate: 0.1,
                    updated_at: '2026-05-10T00:00:00Z',
                    last_swept_at: '2026-05-12T00:00:00Z',
                    created_by: alice,
                }),
                '/api/projects/:team_id/vision/scanners/:id/observations/stats/': {
                    ...summarizerStats,
                    monitor: { yes_total: 12, no_total: 130, inconclusive_total: 0 },
                    labels: {
                        ...summarizerStats.labels,
                        version_markers: [
                            {
                                date: '2026-05-01',
                                version: 3,
                                prompt: 'Did the user struggle?',
                                scanner_config: { prompt: 'Did the user struggle?' },
                                scanner_type: 'monitor',
                                model: 'gemini-3.8-flash',
                                provider: 'google',
                                emits_signals: false,
                                query: null,
                                sampling_rate: 1,
                                sampling_mode: 'comprehensive',
                                up: 6,
                                down: 2,
                                total: 142,
                            },
                        ],
                    },
                } satisfies ObservationStatsApi,
            },
        }),
    ],
}

export const ScannerObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=observations` },
}

// The shared list rows rebuilt for another scanner type: same sessions, people and statuses, with each
// succeeded row carrying that type's output. The failed row keeps its null result.
const observationsFor = (
    scannerResponse: ReplayScannerApi,
    outputs: Record<string, unknown>[]
): typeof observations => {
    let next = 0
    return {
        ...observations,
        results: observations.results.map((row) => ({
            ...row,
            scanner_id: scannerResponse.id,
            scanner_snapshot: {
                ...row.scanner_snapshot,
                name: scannerResponse.name,
                scanner_type: scannerResponse.scanner_type,
                scanner_config: scannerResponse.scanner_config,
            },
            scanner_result: row.scanner_result
                ? {
                      ...row.scanner_result,
                      model_output: { scanner_type: scannerResponse.scanner_type, ...outputs[next++ % outputs.length] },
                  }
                : null,
        })) as ReplayObservationApi[],
    }
}

const observationsTabDecorator = (
    scannerResponse: ReplayScannerApi,
    stats: ObservationStatsApi,
    outputs: Record<string, unknown>[]
): ReturnType<typeof mswDecorator>[] => [
    overviewDecorator(scannerResponse, stats),
    mswDecorator({
        get: {
            '/api/projects/:team_id/vision/scanners/:id/observations/': observationsFor(scannerResponse, outputs),
        },
    }),
]

export const MonitorObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(monitorOverviewScanner.id)}?tab=observations` },
    decorators: observationsTabDecorator(monitorOverviewScanner, monitorOverviewStats, [
        {
            verdict: 'yes',
            confidence: 0.91,
            reasoning: 'Retried the payment form twice and left the page before completing the order.',
        },
        {
            verdict: 'no',
            confidence: 0.84,
            reasoning: 'Moved through checkout in under a minute without errors or backtracking.',
        },
        {
            verdict: 'inconclusive',
            confidence: 0.4,
            reasoning: 'The recording ends on the shipping step, so the outcome is unclear.',
        },
    ]),
}

export const ClassifierObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(classifierOverviewScanner.id)}?tab=observations` },
    decorators: observationsTabDecorator(classifierOverviewScanner, classifierOverviewStats, [
        {
            tags: ['rage-click', 'slow-load'],
            tags_freeform: ['coupon-confusion'],
            confidence: 0.88,
            reasoning: 'Clicked the disabled submit button repeatedly while the shipping rates loaded.',
        },
        {
            tags: ['dead-end'],
            tags_freeform: [],
            confidence: 0.79,
            reasoning: 'Opened the returns page from the footer and found no way back to the cart.',
        },
        { tags: [], tags_freeform: [], confidence: 0.72, reasoning: 'A short browse with no friction.' },
    ]),
}

export const ScorerObservations: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(scorerOverviewScanner.id)}?tab=observations` },
    decorators: observationsTabDecorator(scorerOverviewScanner, scorerOverviewStats, [
        { score: 8.5, confidence: 0.86, reasoning: 'Compared plans, opened billing and invited a teammate.' },
        { score: 2, confidence: 0.8, reasoning: 'Bounced from the pricing page after a few seconds.' },
        { score: 5.5, confidence: 0.7, reasoning: 'Read the docs at length but never started a trial.' },
    ]),
}

export const ScannerOnDemand: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=run` },
}

// Test arms of the model tier-naming experiment: models labeled by capability tier instead of
// provider names, as the Overview's Setup card shows them.
export const ScannerSetupTierNames: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(summarizerScanner.id),
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT]: 'test' },
    },
}

export const ScannerSetupLiteStandardPro: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(summarizerScanner.id),
        featureFlags: {
            [FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT]: 'lite-standard-pro',
        },
    },
}

// Renders the pending recommendation's diff and change cards plus the rating list.
export const ScannerCalibration: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=calibration` },
}

export const ScannerCalibrationTestNudge: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=calibration`,
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_TEST_NUDGE]: 'test' },
    },
}

const neverRatedStats = {
    ...summarizerStats,
    labels: { ...summarizerStats.labels, up_total: 0, down_total: 0 },
}

export const ScannerCalibrationActivationBadge: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(summarizerScanner.id),
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_ACTIVATION]: 'badge' },
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/scanners/:id/observations/stats/': neverRatedStats },
        }),
    ],
}

export const ScannerCalibrationActivationPrompt: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(summarizerScanner.id),
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_ACTIVATION]: 'prompt' },
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/scanners/:id/observations/stats/': neverRatedStats },
        }),
    ],
}

const digestScoutConfig = {
    id: '00000000-0000-0000-0000-0000000000c1',
    skill_name: 'signals-scout-daily-digest-confused-checkout',
    display_name: 'Checkout / daily digest',
    description: 'Daily digest of what the scanner observed since the last run.',
    scout_origin: 'custom',
    owners: [alice],
    enabled: true,
    status: 'active',
    pause_reason: null,
    source_product: 'replay_vision',
    source_id: summarizerScanner.id,
    run_cron_schedule: '0 9 * * *',
    run_interval_minutes: 1440,
    output_destinations: {},
    created_at: '2026-05-02T09:00:00Z',
}

const trendScoutConfig = {
    ...digestScoutConfig,
    id: '00000000-0000-0000-0000-0000000000c2',
    skill_name: 'signals-scout-checkout-trend-watch',
    display_name: '',
    description: 'Watches for week-over-week movement in checkout friction themes.',
    owners: [bob],
    created_at: '2026-05-06T09:00:00Z',
}

const scoutReport = {
    report_id: '00000000-0000-0000-0000-0000000000d1',
    title: 'Daily digest confused checkout: 2026-05-12',
    summary: '**TL;DR:** Checkout friction held steady; coupon box confusion dominated.',
    skill_name: digestScoutConfig.skill_name,
    filed_at: '2026-05-12T09:00:00Z',
    charts: [],
    created_at: '2026-05-12T09:03:00Z',
    updated_at: '2026-05-12T09:03:00Z',
}

// A realistic multi-section digest in the Overview's side column, so its clamp and "Show full report" render.
export const MonitorOverviewWithScoutReport: StoryObj = {
    parameters: { pageUrl: urls.replayVision(monitorOverviewScanner.id) },
    decorators: [
        overviewDecorator(monitorOverviewScanner, monitorOverviewStats, activeSelfDrivingStats),
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/scout/configs/': [
                    { ...digestScoutConfig, source_id: monitorOverviewScanner.id },
                ],
                '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [
                    {
                        ...scoutReport,
                        summary: [
                            '**TL;DR:** Yes verdicts rose from 22% to 27% this week, driven by the new shipping step.',
                            '',
                            '**What changed**',
                            '',
                            '[Yes verdicts by day](chart:yes-by-day)',
                            '',
                            '- 14 sessions stalled on the shipping options screen after the address form reset.',
                            '- Coupon errors fell to 3 sessions, down from 11 before the validation fix.',
                            '- Mobile Safari accounts for 9 of the 14 shipping stalls.',
                            '',
                            '**Worth a look**',
                            '- The address form clears the postcode when the user goes back a step.',
                            '- Two sessions retried payment four times before giving up.',
                            '',
                            '**Unchanged**',
                            '- Card declines stayed flat at about 2% of checkouts.',
                        ].join('\n'),
                        charts: [
                            {
                                chart_id: 'yes-by-day',
                                title: 'Yes verdicts by day',
                                caption: 'The rise starts the day the new shipping step shipped.',
                                query: {
                                    kind: 'InsightVizNode',
                                    source: {
                                        kind: 'TrendsQuery',
                                        series: [
                                            { kind: 'EventsNode', event: '$recording_observed', name: 'Yes verdicts' },
                                        ],
                                        dateRange: { date_from: '2026-04-29', date_to: '2026-05-12' },
                                    },
                                },
                            },
                            {
                                chart_id: 'stalls-by-browser',
                                title: 'Shipping stalls by browser',
                                query: {
                                    kind: 'InsightVizNode',
                                    source: {
                                        kind: 'TrendsQuery',
                                        series: [{ kind: 'EventsNode', event: '$recording_observed', name: 'Stalls' }],
                                        trendsFilter: { display: 'ActionsBarValue' },
                                        dateRange: { date_from: '2026-04-29', date_to: '2026-05-12' },
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
        }),
    ],
}

export const ScannerScouts: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=scouts`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/signals/scout/configs/': [digestScoutConfig, trendScoutConfig],
                '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [scoutReport],
                '/api/projects/:team_id/llm_skills/name/:skillName/': {
                    body: 'Review new scanner observations and report changes in checkout friction.',
                },
            },
        }),
    ],
}

export const ScannerScoutsEmpty: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=scouts`,
    },
}

const metricAlert = {
    id: '00000000-0000-0000-0000-0000000000e1',
    scanner_id: summarizerScanner.id,
    name: 'Coupon friction spike',
    enabled: true,
    kind: 'metric',
    selection: {},
    metric: 'count',
    direction: 'above',
    threshold: 10,
    window_days: 1,
    check_interval_minutes: 60,
    state: 'not_firing',
    evaluation_periods: 1,
    notification_config: [],
    created_at: '2026-05-03T00:00:00Z',
    updated_at: '2026-05-03T00:00:00Z',
    created_by: alice,
}

const matchAlert = {
    ...metricAlert,
    id: '00000000-0000-0000-0000-0000000000e2',
    name: 'Any rage click observation',
    kind: 'match',
    metric: null,
    direction: null,
    threshold: null,
    state: 'firing',
    created_by: bob,
}

export const ScannerAlerts: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=alerts`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/alerts/': {
                    count: 2,
                    next: null,
                    previous: null,
                    results: [metricAlert, matchAlert],
                },
            },
        }),
    ],
}

export const ScannerAlertsEmpty: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=alerts`,
    },
}

export const ScannerTemplates: StoryObj = {
    parameters: { pageUrl: urls.replayVisionTemplates() },
}

export const ScannerEditorDetails: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerDetails(summarizerScanner.id) },
}

export const ScannerEditorConfigure: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerConfigure(summarizerScanner.id) },
}

export const ScannerEditorConfigureTierNames: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerConfigure(summarizerScanner.id),
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT]: 'test' },
    },
}

export const ScannerEditorConfigureLiteStandardPro: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerConfigure(summarizerScanner.id),
        featureFlags: {
            [FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT]: 'lite-standard-pro',
        },
    },
}

export const ScannerEditorTriggers: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerTriggers(summarizerScanner.id) },
}

export const ScannerEditorBudget: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerBudget(summarizerScanner.id) },
}

export const ObservationDetail: StoryObj = {
    parameters: { pageUrl: urls.replayVisionObservation(observationDetail.id) },
}

// The only story covering the collapsed prompt row and the pinned session properties card.
export const ObservationDetailMonitor: StoryObj = {
    parameters: { pageUrl: urls.replayVisionObservation(monitorObservationDetail.id) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/observations/:id/': monitorObservationDetail,
            },
        }),
    ],
}

export const ObservationDetailCalibrationEntryPoint: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionObservation(observationDetail.id),
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_ENTRY_POINT]: 'test' },
    },
}

export const ObservationDetailFeedbackPrompt: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionObservation(thumbsDownObservationDetail.id),
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_CALIBRATION_FEEDBACK_PROMPT]: 'test' },
    },
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/vision/observations/:id/': thumbsDownObservationDetail },
        }),
    ],
}

// Billing hasn't clamped this org's limit yet, so the API still reports it as uncapped.
export const StartupProgramCap: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tags/': ['checkout', 'core flows'],
                '/api/projects/:team_id/vision/scanners/': scanners,
                '/api/projects/:team_id/vision/scanners/stats/': scannerStats,
                '/api/projects/:team_id/vision/quota/': { ...quota, credit_limit: null, remaining: null },
                '/api/billing/': { ...billingJson, startup_program_label: StartupProgramLabel.YC },
            },
        }),
    ],
}

// The goal-based creation flow when the flag's test variant is on: the two questions (goal, budget)
// lead, with the template gallery kept below them as a start-from-a-template alternative.
export const ScannerEditorGoalFlow: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerTemplate('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_BASED_CREATION_FLOW]: 'test' },
    },
}

const goalDraft: DraftScannerResponseApi = {
    name: 'Billing give-up monitor',
    description: 'Flags sessions where a user reaches billing and leaves without finishing.',
    scanner_type: 'monitor',
    scanner_config: {
        prompt: 'Did the user reach a billing page and leave without completing what they started there? Answer yes or no with a one-sentence reason.',
        allow_inconclusive: true,
    },
    rationale:
        'You want to catch people who give up around billing, so this watches sessions that touch your billing pages and asks a yes/no question about each one. Giving up looks unremarkable, so it watches all matching replays rather than only the eventful ones.',
    query: {
        kind: 'RecordingsQuery',
        properties: [
            {
                type: 'recording',
                key: 'visited_page',
                value: ['/organization/billing/overview', '/organization/billing/plans', '/checkout'],
                operator: 'icontains',
            },
        ],
    },
    sampling_mode: 'comprehensive',
    sampling_rate: 0.25,
    model: 'gemini-3-flash-preview',
    credit_limit: 5000,
    experiment_targeting: null,
    estimated_monthly_observations: 1000,
}

// The landing step after a goal draft: the whole config ordered by comprehension, each section
// deep-linking into the wizard step that edits it. Seeded through the same action the loader fires.
export const ScannerEditorGoalOverview: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_BASED_CREATION_FLOW]: 'test' },
    },
    decorators: [
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            // The success listener's stale-navigation guard sees the overview URL and skips its own
            // reset + redirect, so only the goalDraft reducer applies; the form is seeded by hand.
            logic.actions.draftScannerFromGoalSuccess(goalDraft)
            logic.actions.setScannerValues({
                name: goalDraft.name,
                description: goalDraft.description,
                scanner_type: goalDraft.scanner_type as ScannerType,
                scanner_config: goalDraft.scanner_config as ScannerConfig,
                query: goalDraft.query as RecordingsQuery,
                sampling_mode: goalDraft.sampling_mode as SamplingMode,
                sampling_rate: goalDraft.sampling_rate ?? 1,
            })
            return <StoryFn />
        },
    ],
}

// The same landing step for a goal that named an experiment: the eligible-recordings section
// leads with the experiment and variant the scan watches, which no page filter can express.
export const ScannerEditorGoalOverviewExperiment: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_BASED_CREATION_FLOW]: 'test' },
    },
    decorators: [
        mswDecorator({
            get: {
                // The targeting card and the snack read the experiment's name from this fetch.
                '/api/projects/:team_id/experiments/:id/': {
                    id: 11,
                    name: 'AI-based scanner creation',
                    description: 'Does the goal flow beat the template gallery?',
                    feature_flag_key: 'vision-goal-based-creation-flow',
                    feature_flag: {
                        id: 11,
                        key: 'vision-goal-based-creation-flow',
                        filters: {
                            multivariate: {
                                variants: [
                                    { key: 'control', rollout_percentage: 50 },
                                    { key: 'test', rollout_percentage: 50 },
                                ],
                            },
                        },
                    },
                    start_date: '2026-09-01T00:00:00Z',
                    end_date: null,
                    exposure_criteria: {},
                },
            },
        }),
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            const draft: DraftScannerResponseApi = {
                ...goalDraft,
                name: 'New creation flow friction',
                description: 'Flags sessions where a participant struggles in the new AI creation flow.',
                scanner_config: {
                    prompt: 'Did the participant hesitate, backtrack, or give up while describing their goal in the scanner creation flow? Answer yes or no with a one-sentence reason.',
                    allow_inconclusive: true,
                },
                rationale:
                    'Your goal is about the new AI creation flow, so this watches only the sessions of people the experiment put in its test variant, on the pages where that flow lives. Struggling looks unremarkable, so it watches all matching replays rather than only the eventful ones.',
                query: {
                    kind: 'RecordingsQuery',
                    properties: [
                        {
                            type: 'recording',
                            key: 'visited_page',
                            value: ['/replay-vision/scanners/new'],
                            operator: 'icontains',
                        },
                    ],
                    events: [
                        {
                            id: 'replay_vision_scanner_creation_started',
                            name: 'replay_vision_scanner_creation_started',
                            type: 'events',
                            order: 0,
                        },
                    ],
                } as RecordingsQuery,
                experiment_targeting: { experiment_id: 11, variant: 'test' },
            }
            logic.actions.draftScannerFromGoalSuccess(draft)
            logic.actions.setScannerValues({
                name: draft.name,
                description: draft.description,
                scanner_type: draft.scanner_type as ScannerType,
                scanner_config: draft.scanner_config as ScannerConfig,
                query: draft.query as RecordingsQuery,
                sampling_mode: draft.sampling_mode as SamplingMode,
                sampling_rate: draft.sampling_rate ?? 1,
                experiment_targeting: draft.experiment_targeting,
            })
            return <StoryFn />
        },
    ],
}

// The overview while the draft is still generating: the loading bar and skeleton the user sees
// right after submitting the two questions.
export const ScannerEditorGoalOverviewLoading: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerOverview('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_BASED_CREATION_FLOW]: 'test' },
    },
    decorators: [
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            // Hold the draft loader open so the overview renders its skeleton instead of a result.
            logic.actions.draftScannerFromGoal('find out where people give up in billing', 5000)
            return <StoryFn />
        },
    ],
}
