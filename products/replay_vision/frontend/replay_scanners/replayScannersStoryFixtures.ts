import type { Meta } from '@storybook/react'

import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'

import scoutTemplates from '../__mocks__/scoutTemplates.json'
import type {
    BackfillEstimateResponseApi,
    ExperimentVariantsReadoutApi,
    ObservationStatsApi,
    ReplayObservationApi,
    ReplayScannerApi,
    ReplayScannerBackfillApi,
    ScannerSelfDrivingStatsApi,
    ScannerStatsResponseApi,
    UserBasicApi,
    VisionQuotaApi,
} from '../generated/api.schemas'

export const alice: UserBasicApi = {
    id: 1,
    uuid: '00000000-0000-0000-0000-000000000001',
    first_name: 'Alice',
    last_name: 'Anderson',
    email: 'alice@example.com',
    hedgehog_config: null,
}

export const bob: UserBasicApi = {
    id: 2,
    uuid: '00000000-0000-0000-0000-000000000002',
    first_name: 'Bob',
    last_name: 'Brown',
    email: 'bob@example.com',
    hedgehog_config: null,
}

export const scanner = (overrides: Partial<ReplayScannerApi> = {}): ReplayScannerApi =>
    ({
        id: '00000000-0000-0000-0000-00000000000a',
        name: 'Scanner',
        description: '',
        tags: [],
        scanner_type: 'monitor',
        scanner_config: { prompt: 'Did the user struggle?' },
        prompt_question: 'Did the user struggle?',
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
        // Older than the Overview's 14-day default, so its range matches the 14 days in the trend mock.
        created_at: '2026-04-01T00:00:00Z',
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
        sweep_interval_minutes: 5,
        dashboard_id: null,
        dashboard_suggested: false,
        ...overrides,
    }) as ReplayScannerApi

export const scanners = {
    count: 4,
    next: null,
    previous: null,
    results: [
        scanner({
            id: '00000000-0000-0000-0000-00000000000a',
            name: 'Confused checkout',
            credits_this_month: 1250,
            prompt_question: 'Did the user hesitate at checkout?',
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
            prompt_question: 'Which frustration patterns appear in this session?',
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
            prompt_question: 'What happened in this session?',
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
            prompt_question: 'How strong is the buying intent in this session?',
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

export const scannerStats: ScannerStatsResponseApi = {
    total: 4,
    enabled: 3,
    by_type: {
        monitor: { enabled: 1, total: 1 },
        classifier: { enabled: 0, total: 1 },
        scorer: { enabled: 1, total: 1 },
        summarizer: { enabled: 1, total: 1 },
        experiment: { enabled: 0, total: 0 },
    },
}

export const quota: VisionQuotaApi = {
    credit_limit: 10000,
    credits_used: 2400,
    remaining: 7600,
    exhausted: false,
    projected_monthly_credits: 5200,
    scanners_monthly_credits: 5200,
    scanners_period_credits: 3467,
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

export const summarizerScanner = scanners.results[2]

export const summarizerStats: ObservationStatsApi = {
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

export const monitorOverviewScanner: ReplayScannerApi = {
    ...scanners.results[0],
    prompt_question: 'Did the user struggle to complete checkout?',
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

export const rootCauseFormScanner: ReplayScannerApi = {
    ...monitorOverviewScanner,
    id: '00000000-0000-0000-0000-0000000000aa',
}

export const monitorOverviewStats: ObservationStatsApi = {
    ...summarizerStats,
    monitor: { yes_total: 38, no_total: 97, inconclusive_total: 7 },
}

export const classifierOverviewScanner: ReplayScannerApi = {
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

export const classifierOverviewStats: ObservationStatsApi = {
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

export const scorerOverviewScanner: ReplayScannerApi = {
    ...scanners.results[3],
    credit_limit: 400,
    credits_used_against_limit: 399,
    limit_reached: true,
}

export const scorerOverviewStats: ObservationStatsApi = {
    ...summarizerStats,
    scorer: {
        summary: { min: 0.5, p25: 3.2, median: 5.1, mean: 5.3, p75: 7.4, max: 9.8, count: 142 },
        histogram: {
            labels: ['0-1', '1-2', '2-3', '3-4', '4-5', '5-6', '6-7', '7-8', '8-9', '9-10'],
            counts: [2, 5, 11, 19, 27, 30, 22, 14, 8, 4],
        },
    },
}

export const overviewDecorator = (
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

export const observation = (overrides: Partial<ReplayObservationApi> = {}): ReplayObservationApi =>
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
        prompt_question: null,
        prompt_valence: null,
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
                video_start_ms: 24000,
            },
        ],
        ...overrides,
    }) as ReplayObservationApi

export const observations = {
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

// The detail pages show the prompt beside the answer, so these read like prompts people write.
const SUMMARIZER_DETAIL_PROMPT = [
    'Summarize this session for the product team reviewing checkout drop-off.',
    '',
    'Start with one sentence on what the user was trying to do and whether they got there. Then walk through the key moments in order: where they spent the most time, where they hesitated or went back, and any errors, empty states, or slow loads they ran into.',
    '',
    'Call out anything that looks like a bug rather than user confusion, such as a button that does nothing, a form that clears itself, or a page that never finishes loading. Quote the exact error text when it is visible on screen.',
    '',
    'Keep it factual. Do not guess at intent beyond what the recording shows, and do not recommend fixes. If the session is mostly idle or the user never reaches checkout, say so in one sentence and stop.',
].join('\n')

// Standalone detail-page observation with long unbroken identifiers, prev/next nav, and a rating.
export const observationDetail = observation({
    id: '00000000-0000-0000-0000-0000000000d1',
    session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d08',
    recording_subject_email: 'very.long.customer.email.address@enterprise-customer-company-name.example.com',
    distinct_id: 'enterprise-user-with-a-very-long-distinct-id-8f3k2j9d2m1x',
    previous_observation_id: '00000000-0000-0000-0000-0000000000b1',
    next_observation_id: '00000000-0000-0000-0000-0000000000b4',
    label: { is_correct: true, feedback: 'Good catch on the coupon error.' },
    prompt_question: 'What happened in this session around checkout drop-off?',
    scanner_snapshot: {
        ...observation().scanner_snapshot!,
        scanner_config: { prompt: SUMMARIZER_DETAIL_PROMPT, length: 'medium' },
    },
    scanner_result: {
        model_output: {
            scanner_type: 'summarizer',
            confidence: 0.87,
            title: 'Coupon validation loop at checkout',
            summary:
                'The user spent most of the session in checkout, retrying an invalid coupon three times before abandoning the cart at the payment step.',
        },
        signals_count: 1,
    },
})

// The pinned strip's default pins, in order: three session columns then a geo event property.
// The values are invented.
const sessionPropertiesRow = ['google.com', 'Paid Search', 'google', 'US']

export const estimate = {
    matched_sessions_in_window: 1840,
    window_days: 30,
    estimated_observations_per_month: 92,
    credits_per_observation: 1,
    estimated_credits_per_month: 92,
    other_enabled_scanners_monthly_credits: 5108,
    free_only_monthly_credits_left: 2500,
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
            order: 0,
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

// The Variants tab of an experiment scanner. The data is invented: a checkout experiment with
// balanced sampling, so the smaller variant shows a higher sampling rate.
export const experimentScanner: ReplayScannerApi = scanner({
    id: '00000000-0000-0000-0000-0000000000e1',
    name: 'Post-exposure friction: New checkout flow',
    scanner_type: 'experiment',
    scanner_config: {
        prompt: 'Summarize what this participant did after they reached the checkout.',
        length: 'medium',
        experiment_id: 11,
        variants: null,
        balance_variants: true,
    },
    observations_this_month: 71,
})

const experimentObservation = (
    id: string,
    variant: string,
    title: string,
    email: string,
    createdAt: string
): ReplayObservationApi =>
    observation({
        id,
        scanner_id: experimentScanner.id,
        recording_subject_email: email,
        created_at: createdAt,
        scanner_snapshot: {
            ...observation().scanner_snapshot!,
            name: experimentScanner.name,
            scanner_type: 'experiment',
        },
        scanner_result: {
            model_output: {
                scanner_type: 'experiment',
                confidence: 0.9,
                title,
                summary: `${title} The session ends on the order confirmation page.`,
            },
            signals_count: 0,
            experiment_variant: variant,
        } as ReplayObservationApi['scanner_result'],
    })

export const readyAnalysis = {
    scout_config_id: '00000000-0000-0000-0000-0000000000s1',
    scout_enabled: true,
    recorded_at: '2026-05-11T09:00:00Z',
    scanner_version: 1,
    current: true,
}

export const variantsReadout = (
    overrides: Partial<ExperimentVariantsReadoutApi> = {}
): ExperimentVariantsReadoutApi => ({
    experiment: {
        id: 11,
        name: 'New checkout flow',
        status: 'running',
        start_date: '2026-05-03T00:00:00Z',
        end_date: null,
        planned_duration_days: 21,
        current_day: 9,
    },
    window: {
        total_observations: 71,
        first_observation_at: '2026-05-03T10:00:00Z',
        last_observation_at: '2026-05-11T20:48:00Z',
    },
    variants: [
        {
            key: 'control',
            observations: 34,
            distinct_people: 31,
            median_session_duration_s: 250,
            sampling_rate: 0.12,
            analysis_observations: 34,
            digest: [
                {
                    theme: 'first-try-payment',
                    statement: 'Most people complete payment on the first try.',
                    count: 21,
                    read: null,
                    example_observation_ids: ['00000000-0000-0000-0000-0000000000c1'],
                },
                {
                    theme: 'summary-rereads',
                    statement: 'Some people scroll the order summary twice before they pay.',
                    count: 8,
                    read: null,
                    example_observation_ids: [],
                },
            ],
            latest_observations: [
                experimentObservation(
                    '00000000-0000-0000-0000-0000000000c1',
                    'control',
                    'Adds two items, opens the cart, and completes payment in one pass.',
                    'mia@example.com',
                    '2026-05-11T20:34:00Z'
                ),
                experimentObservation(
                    '00000000-0000-0000-0000-0000000000c2',
                    'control',
                    'Reviews the order summary twice, edits the quantity, then pays.',
                    'noah@example.com',
                    '2026-05-11T19:50:00Z'
                ),
            ],
        },
        {
            key: 'test',
            observations: 31,
            distinct_people: 29,
            median_session_duration_s: 340,
            sampling_rate: 0.4,
            analysis_observations: 31,
            digest: [
                {
                    theme: 'payment-method-pause',
                    statement: 'Many people pause at the payment method step before they select an option.',
                    count: 11,
                    read: null,
                    example_observation_ids: ['00000000-0000-0000-0000-0000000000t1'],
                },
                {
                    theme: 'promo-field',
                    statement: 'Several people open and close the promo code field without entering a code.',
                    count: 7,
                    read: null,
                    example_observation_ids: [],
                },
            ],
            latest_observations: [
                experimentObservation(
                    '00000000-0000-0000-0000-0000000000t1',
                    'test',
                    'Reaches the payment method step and moves between two options for about 40 seconds before selecting a card.',
                    'ava@example.com',
                    '2026-05-11T20:48:00Z'
                ),
            ],
        },
    ],
    differences: [
        {
            theme: 'payment-method-pause',
            statement: 'Pauses at the payment method step appear far more often in test.',
            counts: { test: 11, control: 2 },
            read: {},
        },
        {
            theme: 'promo-field',
            statement: 'Promo code interactions appear only in test.',
            counts: { test: 7, control: 0 },
            read: {},
        },
    ],
    unattributed_count: 6,
    analysis: readyAnalysis,
    ...overrides,
})

export const variantsDecorator = (readout: ExperimentVariantsReadoutApi): ReturnType<typeof mswDecorator> =>
    mswDecorator({
        get: {
            '/api/projects/:team_id/vision/scanners/:id/': experimentScanner,
            '/api/projects/:team_id/vision/scanners/:id/variants/': readout,
            '/api/projects/:team_id/vision/scanners/:id/observations/stats/': summarizerStats,
            '/api/projects/:team_id/vision/scanners/:id/self_driving_stats/': noSelfDrivingStats,
            '/api/projects/:team_id/experiments/:id/': {
                id: 11,
                name: 'New checkout flow',
                feature_flag_key: 'new-checkout-flow',
                start_date: '2026-05-03T00:00:00Z',
            },
        },
    })

const runningExperiments = {
    count: 2,
    next: null,
    previous: null,
    results: [
        { id: 11, name: 'AI creation flow', feature_flag: { filters: {} } },
        { id: 12, name: 'Pricing page layout', feature_flag: { filters: {} } },
    ],
}

export const replayScannersStoryConfig: Pick<Meta, 'parameters' | 'decorators'> = {
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-05-12',
        pageUrl: urls.replayVision(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tags/': { results: ['checkout', 'core flows'], next: null, count: 2 },
                '/api/projects/:team_id/experiments/': runningExperiments,
                '/api/projects/:team_id/vision/scanners/': scanners,
                '/api/projects/:team_id/vision/scanners/stats/': scannerStats,
                '/api/projects/:team_id/vision/scanners/creators/': { creators: [alice, bob] },
                // Two picks, then each filler kind. Only the first carries a key moment, so the rest show no time on the tile.
                '/api/projects/:team_id/vision/scanners/highlight_feed/': {
                    results: [
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d1',
                                prompt_question: 'Did the user hesitate at checkout?',
                                scanner_id: scanners.results[0].id,
                                scanner_snapshot: {
                                    name: 'Confused checkout',
                                    scanner_type: 'monitor',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: true,
                                    scanner_config: { prompt: 'Did the user hesitate at checkout?' },
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
                                        key_moment_ms: 154000,
                                    },
                                    signals_count: 2,
                                },
                                viewed: false,
                            }),
                            reason: { kind: 'embedding_pick', watch_category: 'failure', similar_count: 0 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d2',
                                prompt_question: 'How strong is the buying intent in this session?',
                                scanner_id: scanners.results[3].id,
                                scanner_snapshot: {
                                    name: 'Intent score',
                                    scanner_type: 'scorer',
                                    scanner_version: 1,
                                    model: 'gemini-3.8-flash',
                                    provider: 'google',
                                    emits_signals: false,
                                    scanner_config: { prompt: 'Score this session.', scale: { min: 0, max: 10 } },
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
                                },
                                viewed: false,
                            }),
                            reason: { kind: 'embedding_pick', watch_category: 'revenue', similar_count: 0 },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d3',
                                prompt_question: 'What happened in this session?',
                                recording_subject_email: 'bob@example.com',
                                viewed: true,
                            }),
                            reason: { kind: 'unviewed_recent' },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000d4',
                                prompt_question: 'What happened in this session?',
                                scanner_result: {
                                    model_output: {
                                        scanner_type: 'summarizer',
                                        confidence: 0.8,
                                        title: 'Quick bug report',
                                        summary: 'Hit an error dialog and filed feedback from the toast.',
                                    },
                                    signals_count: 0,
                                },
                                viewed: true,
                            }),
                            reason: { kind: 'recent' },
                        },
                    ],
                },
                '/api/projects/:team_id/vision/quota/': quota,
                '/api/projects/:team_id/vision/quota/spend_series/': spendSeries,
                '/api/projects/:team_id/vision/scanners/:id/': ({ params }) =>
                    params.id === rootCauseFormScanner.id
                        ? rootCauseFormScanner
                        : params.id === monitorOverviewScanner.id
                          ? monitorOverviewScanner
                          : summarizerScanner,
                // Rendered by the backend's templates; only the root cause body is full, since only its form is shown.
                '/api/projects/:team_id/vision/scanners/:scannerId/scouts/templates/': ({ params }) =>
                    (params.scannerId === summarizerScanner.id
                        ? scoutTemplates.summarizer
                        : scoutTemplates.monitor
                    ).map((template) => ({
                        ...template,
                        body: template.body.replaceAll('SCANNER_ID', String(params.scannerId)),
                    })),
                '/api/projects/:team_id/vision/scanners/:id/self_driving_stats/': noSelfDrivingStats,
                '/api/projects/:team_id/vision/scanners/:id/observations/': observations,
                '/api/projects/:team_id/vision/scanners/:id/observations/stats/': ({ params }) =>
                    params.id === rootCauseFormScanner.id || params.id === monitorOverviewScanner.id
                        ? monitorOverviewStats
                        : summarizerStats,
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
                // The observation page embeds the player, so it needs a recording to play.
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) =>
                    new URL(request.url).searchParams.get('source') === 'blob_v2'
                        ? new Response(snapshotsAsJSONLines())
                        : {
                              sources: [
                                  {
                                      source: 'blob_v2',
                                      start_timestamp: '2023-08-11T12:03:36.097000Z',
                                      end_timestamp: '2023-08-11T12:04:52.268000Z',
                                      blob_key: '0',
                                  },
                              ],
                          },
                '/api/environments/:team_id/session_recordings/:id': recordingMetaJson,
                '/api/projects/:team_id/property_definitions/': ({ request }) => {
                    const type = new URL(request.url).searchParams.get('type')
                    return type === 'person'
                        ? paginated(['email', 'plan', 'company_size'])
                        : paginated(['$geoip_country_code', '$browser', '$device_type', '$os'])
                },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { kind?: string; query?: string } } | null
                    if (body?.query?.kind === 'EventsQuery') {
                        return recordingEventsJson
                    }
                    // The observation page's pinned strip is the only query aliasing its columns this way.
                    return body?.query?.query?.includes('as pinned_0')
                        ? { results: [sessionPropertiesRow] }
                        : observationsTrend
                },
                '/api/projects/:team_id/vision/observations/:id/label/': async ({ request }) => {
                    const body = (await request.json()) as { is_correct: boolean; feedback?: string }
                    return { is_correct: body.is_correct, feedback: body.feedback ?? '' }
                },
                '/api/projects/:team_id/vision/scanners/estimate/': estimate,
                '/api/projects/:team_id/vision/scanners/:scannerId/backfills/estimate/': backfillEstimate,
            },
        }),
    ],
}

export const digestScoutConfig = {
    id: '00000000-0000-0000-0000-0000000000c1',
    skill_name: 'signals-scout-daily-digest-confused-checkout',
    display_name: 'Checkout / daily digest',
    description: 'Daily digest of what the scanner observed since the last run.',
    scout_origin: 'custom',
    owners: [alice],
    enabled: true,
    status: 'active',
    pause_reason: null,
    managed_by: 'team',
    source_product: 'replay_vision',
    source_id: summarizerScanner.id,
    run_cron_schedule: '0 9 * * *',
    run_interval_minutes: 1440,
    output_destinations: {},
    created_at: '2026-05-02T09:00:00Z',
}

export const freeCreditsUsedQuota: VisionQuotaApi = {
    ...quota,
    credits_used: 2600,
    credits_settled: 2600,
    remaining: 7400,
}

export const freeOnlyScanner: ReplayScannerApi = {
    ...summarizerScanner,
    id: '00000000-0000-0000-0000-00000000000e',
    name: 'Free checkout summaries',
    free_only: true,
    credit_limit: null,
    credits_used_against_limit: 600,
    limit_reached: false,
}

export const freeOnlyLimitReachedScanner: ReplayScannerApi = {
    ...freeOnlyScanner,
    credits_used_against_limit: 2600,
    limit_reached: true,
}
