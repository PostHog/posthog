import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingMetaJson } from 'scenes/session-recordings/__mocks__/recording_meta'
import { snapshotsAsJSONLines } from 'scenes/session-recordings/__mocks__/recording_snapshots'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { sessionFrameResponse } from '~/mocks/fixtures/sessionFrame'
import { RecordingsQuery } from '~/queries/schema/schema-general'
import { StartupProgramLabel } from '~/types'

import { expect } from 'storybook/test'

import { LONG, LONG_INACTIVE, summary as timelineSummary } from '../__mocks__/recordingTimelineObservations'
import type {
    BackfillEstimateResponseApi,
    DraftScannerResponseApi,
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

const scannerStats: ScannerStatsResponseApi = {
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

const rootCauseFormScanner: ReplayScannerApi = {
    ...monitorOverviewScanner,
    id: '00000000-0000-0000-0000-0000000000aa',
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

const MONITOR_DETAIL_PROMPT = [
    'Did the user struggle to complete checkout?',
    '',
    'Answer yes if the user shows clear friction on the cart, shipping, or payment steps. Count any of these as friction:',
    '- Entering a coupon or gift card code more than once after a validation error',
    '- Resubmitting the payment form after an error message',
    '- Moving back and forth between the cart and the payment step without completing the order',
    '- Rage-clicking a disabled or unresponsive button, such as Place order while shipping rates load',
    '- Leaving the site within a minute of seeing an error message',
    '',
    'Answer no if the user completes the order without going back, or browses the cart and leaves without trying to pay. Leaving without paying is not struggling on its own.',
    '',
    'Answer inconclusive if the recording ends before the user reaches a decision, or if most of the checkout is masked.',
    '',
    'Ignore sessions from internal staff accounts and sessions shorter than ten seconds.',
].join('\n')

const CLASSIFIER_DETAIL_PROMPT = [
    'Tag this session with every friction pattern that clearly appears in it. A session can have several tags or none.',
    '',
    '- rage-click: three or more fast clicks on the same element when it does not respond',
    '- dead-end: the user reaches a page with no obvious next step and leaves or goes back',
    '- slow-load: a page or component takes more than about five seconds to show content while the user waits',
    '- form-error: a validation or submit error appears on a form the user is filling in',
    '',
    'Only tag what you can see in the recording, and leave out borderline cases. When a clear friction pattern fits none of these tags, add a short freeform tag in kebab-case instead of forcing it into the closest match.',
].join('\n')

const SCORER_DETAIL_PROMPT = [
    'Score how strong the buying intent in this session is, from 0 to 10.',
    '',
    'Score high (8 to 10) when the user takes steps that only make sense before paying: comparing plans on the pricing page, opening billing settings, entering payment details, or inviting teammates to the workspace.',
    '',
    'Score in the middle (4 to 7) when the user explores the product in depth, for example building a dashboard or reading the docs for several minutes, but never goes near pricing or billing.',
    '',
    'Score low (0 to 3) for short visits, sessions that bounce from the landing page, or sessions spent mostly in account settings unrelated to billing.',
    '',
    'Base the score only on what happens in this recording, not on how old the account is. Give a short label that names the level of intent.',
].join('\n')

// Standalone detail-page observation with long unbroken identifiers, prev/next nav, and a rating.
const observationDetail = observation({
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

// A monitor observation, so the detail page renders the prompt row and the reasoning card that a
// summarizer hides. The prompt and reasoning are long on purpose, so both clips show. Other stories
// keep the one-paragraph reasoning most scans produce.
const monitorObservationDetail = observation({
    prompt_question: 'Did the user struggle to complete checkout?',
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
            prompt: MONITOR_DETAIL_PROMPT,
            allow_inconclusive: true,
        },
    },
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            confidence: 0.82,
            verdict: 'yes',
            reasoning: [
                'The user reached the cart about a minute into the session and moved to checkout with two items. On the payment step they entered the coupon code SPRING20 and got the error "This code is not valid for items in your cart." They cleared the field and entered it again with the same result, then tried it in lowercase, which failed the same way.',
                '',
                'After the third failure they went back to the cart, removed one item, and returned to payment, which looks like an attempt to make the coupon apply. It still failed. They then filled in the card details and pressed Place order. The page showed a spinner for several seconds and then "Payment could not be processed. Please try again." They submitted the form once more, got the same message, and closed the tab about twenty seconds later.',
                '',
                'This matches three of the friction signals in the prompt: repeated coupon retries after a validation error, going back from payment to the cart, and resubmitting the payment form after an error. The session is not from a staff account and is well over ten seconds long.',
                '',
                'Confidence is below certain because the card fields are masked, so the recording does not show whether the second payment error came from the same input as the first.',
            ].join('\n'),
        },
        signals_count: 1,
    },
})

// The pinned strip's default pins, in order: three session columns then a geo event property.
// The values are invented.
const sessionPropertiesRow = ['google.com', 'Paid Search', 'google', 'US']

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

// The Variants tab of an experiment scanner. The data is invented: a checkout experiment with
// balanced sampling, so the smaller variant shows a higher sampling rate.
const experimentScanner: ReplayScannerApi = scanner({
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

const readyAnalysis = {
    scout_config_id: '00000000-0000-0000-0000-0000000000s1',
    scout_enabled: true,
    recorded_at: '2026-05-11T09:00:00Z',
    scanner_version: 1,
    current: true,
}

const variantsReadout = (overrides: Partial<ExperimentVariantsReadoutApi> = {}): ExperimentVariantsReadoutApi => ({
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
                    example_observation_ids: ['00000000-0000-0000-0000-0000000000c1'],
                },
                {
                    theme: 'summary-rereads',
                    statement: 'Some people scroll the order summary twice before they pay.',
                    count: 8,
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
                    example_observation_ids: ['00000000-0000-0000-0000-0000000000t1'],
                },
                {
                    theme: 'promo-field',
                    statement: 'Several people open and close the promo code field without entering a code.',
                    count: 7,
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
        },
        {
            theme: 'promo-field',
            statement: 'Promo code interactions appear only in test.',
            counts: { test: 7, control: 0 },
        },
    ],
    unattributed_count: 6,
    analysis: readyAnalysis,
    ...overrides,
})

const withoutAnalysis = (readout: ExperimentVariantsReadoutApi): ExperimentVariantsReadoutApi => ({
    ...readout,
    variants: readout.variants.map((variant) => ({ ...variant, digest: null, analysis_observations: null })),
    differences: null,
})

const variantsDecorator = (readout: ExperimentVariantsReadoutApi): ReturnType<typeof mswDecorator> =>
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
                // One card per reason kind. Only the first carries a key moment, so the rest show no time on the tile.
                '/api/projects/:team_id/vision/scanners/watch_feed/': {
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
                            reason: { kind: 'signal_emitted', signals_count: 2 },
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
                            reason: { kind: 'outlier_score', score: 9.5, window_mean: 5.1 },
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
                    experiment: { enabled: 0, total: 0 },
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

const WATCH_FEED_VIEW_STORAGE_KEY = 'products.replay_vision.frontend.replay_scanners.watchFeedLogic.view'

// The same feed as thumbnail cards, each closing with why the recording was picked.
export const HomeWatchFeedGrid: StoryObj = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_HOME_REDESIGN_EXPERIMENT]: 'test' },
    },
    // Seed the saved view before render instead of clicking the toggle: the snapshot build is production
    // React, which has no act(), so testing-library helpers fail there. Remove it afterwards, or every
    // later feed story renders as a grid too.
    beforeEach: () => {
        localStorage.setItem(WATCH_FEED_VIEW_STORAGE_KEY, JSON.stringify('grid'))
        return () => localStorage.removeItem(WATCH_FEED_VIEW_STORAGE_KEY)
    },
}

// The jev ranker arm serves the simplified card: the scan's own sentence plus a scanner chip and
// person line, with the question and verdict behind the chip's tooltip. The first card leads with
// the scan's notability sentence, the second falls back to the derived headline, and the filler
// row reads muted with no finding claim.
export const HomeWatchFeedJevArm: StoryObj = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/scanners/watch_feed/': {
                    ranker: 'jev',
                    results: [
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000e1',
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
                                        key_moment_ms: 154000,
                                    },
                                    signals_count: 0,
                                },
                                viewed: false,
                            }),
                            reason: {
                                kind: 'jev_watchable',
                                jev_probability: 0.91,
                                notability_reason:
                                    'The card form rejected a valid card three times before the user abandoned the checkout.',
                            },
                        },
                        {
                            observation: observation({
                                id: '00000000-0000-0000-0000-0000000000e2',
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
                                    },
                                    signals_count: 0,
                                },
                                viewed: true,
                            }),
                            reason: { kind: 'jev_watchable', jev_probability: 0.48 },
                        },
                        {
                            observation: observation({ id: '00000000-0000-0000-0000-0000000000e3' }),
                            reason: { kind: 'unviewed_recent' },
                        },
                    ],
                },
            },
        }),
    ],
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

// The Scouts tab offers each scanner type only the templates that fit it: root cause for a monitor.
export const MonitorScouts: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(monitorOverviewScanner.id)}?tab=scouts` },
    decorators: [overviewDecorator(monitorOverviewScanner, monitorOverviewStats)],
}

// A summarizer has no outcome to explain, so it gets weekly themes instead of root cause.
export const SummarizerScouts: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=scouts` },
}

// The root cause prompt under the findings opens the create form in place.
export const MonitorRootCauseScoutForm: StoryObj = {
    parameters: { pageUrl: urls.replayVision(rootCauseFormScanner.id) },
    decorators: [overviewDecorator(rootCauseFormScanner, monitorOverviewStats)],
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Add scout'))
        await within(document.body).findByText('New scout: root cause')
    },
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

const observationDetailFor = (
    scannerResponse: ReplayScannerApi,
    id: string,
    output: Record<string, unknown>,
    promptQuestion: string | null = null
): ReplayObservationApi =>
    observation({
        id,
        prompt_question: promptQuestion,
        scanner_id: scannerResponse.id,
        recording_subject_email: 'bob@example.com',
        distinct_id: 'user_2m1x9d',
        previous_observation_id: '00000000-0000-0000-0000-0000000000b1',
        next_observation_id: '00000000-0000-0000-0000-0000000000b4',
        scanner_snapshot: {
            ...observation().scanner_snapshot!,
            name: scannerResponse.name,
            scanner_type: scannerResponse.scanner_type,
            scanner_config: scannerResponse.scanner_config,
        },
        scanner_result: {
            model_output: { scanner_type: scannerResponse.scanner_type, ...output },
            signals_count: 0,
        },
    })

const classifierObservationDetail = observationDetailFor(
    {
        ...classifierOverviewScanner,
        scanner_config: {
            prompt: CLASSIFIER_DETAIL_PROMPT,
            tags: ['rage-click', 'dead-end', 'slow-load', 'form-error'],
            multi_label: true,
            allow_freeform_tags: true,
        },
    },
    '00000000-0000-0000-0000-0000000000d4',
    {
        tags: ['rage-click', 'slow-load'],
        tags_freeform: ['coupon-confusion'],
        confidence: 0.64,
        reasoning:
            'On the shipping step the user pressed the disabled Continue to payment button seven times in about four seconds while the rates were still loading, and the rates took roughly nine seconds to appear, so the step shows both rage-click and slow-load. On payment they entered a coupon code twice and got "Code not recognized" both times, which is tagged coupon-confusion rather than form-error because the form itself submitted fine. There is no dead-end: the user always had a next step and placed the order.',
    },
    'Which friction patterns appear in this session?'
)

const scorerObservationDetail = observationDetailFor(
    {
        ...scorerOverviewScanner,
        scanner_config: { prompt: SCORER_DETAIL_PROMPT, scale: { min: 0, max: 10, label: 'buying intent' } },
    },
    '00000000-0000-0000-0000-0000000000d5',
    {
        score: 8.5,
        label: 'buying intent',
        confidence: 0.41,
        reasoning:
            'The user spent about two minutes on the pricing page comparing the Growth and Enterprise plans, then opened the Billing tab and started to add a card before closing the form. Right after that they invited two teammates from the Members page. Looking at billing and then inviting a team puts this in the high band of the prompt, but not at the top, because the payment details were never saved and the rest of the session was spent back in the product.',
    },
    'How strong is the buying intent in this session?'
)

const observationDetailStory = (detail: ReplayObservationApi): StoryObj => ({
    parameters: { pageUrl: urls.replayVisionObservation(detail.id) },
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/vision/observations/:id/': detail } })],
})

// A scan the model never finished, so the page leads with the failure and a retry instead of a result.
const failedObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d6',
    status: 'failed',
    error_reason: 'provider_transient:The model timed out before returning a result.',
    scanner_result: null,
})

export const ObservationDetailFailed: StoryObj = {
    ...observationDetailStory(failedObservationDetail),
    play: async ({ canvasElement }) => {
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="recording-play"]')).toBeVisible())
        // The floating player controls hide on a timer after mount, so wait for that to happen before the snapshot.
        await waitFor(() => expect(canvasElement.querySelector('[data-attr="recording-play"]')).not.toBeVisible())
    },
}

// The session had no screen data to watch, so no model ran and a later retry may still succeed.
const notScannedObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d7',
    status: 'ineligible',
    error_reason: 'no_snapshots:The recording has no snapshot data yet.',
    scanner_result: null,
})

// A scan still in progress, so the page shows progress where the result goes.
const runningObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d8',
    status: 'running',
    error_reason: '',
    scanner_result: null,
    completed_at: null,
})

export const ObservationDetailNotScanned: StoryObj = observationDetailStory(notScannedObservationDetail)

export const ObservationDetailRunning: StoryObj = {
    ...observationDetailStory(runningObservationDetail),
    // A running scan keeps its progress and status spinners going, so the page never settles for a snapshot.
    tags: ['test-skip'],
}

// The observation outlived its recording, so the player's place explains why and shows the saved frame.
export const ObservationDetailRecordingExpired: StoryObj = {
    parameters: { pageUrl: urls.replayVisionObservation(monitorObservationDetail.id) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/vision/observations/:id/': monitorObservationDetail,
                '/api/environments/:team_id/session_recordings/:id': () => [404, { detail: 'Not found.' }],
            },
        }),
    ],
}

export const ObservationDetailClassifier: StoryObj = observationDetailStory(classifierObservationDetail)

export const ObservationDetailScorer: StoryObj = observationDetailStory(scorerObservationDetail)

export const ScannerOnDemand: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=run` },
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
    managed_by: 'team',
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

const rootCauseScoutConfig = {
    ...digestScoutConfig,
    id: '00000000-0000-0000-0000-0000000000c3',
    skill_name: 'signals-scout-confused-checkout-root-cause',
    display_name: 'Confused checkout root cause',
    source_id: monitorOverviewScanner.id,
    run_cron_schedule: '0 9 * * 1',
}

const rootCauseReport = {
    ...scoutReport,
    report_id: '00000000-0000-0000-0000-0000000000d2',
    title: 'Root cause confused checkout: 2026-05-11',
    skill_name: rootCauseScoutConfig.skill_name,
    filed_at: '2026-05-11T09:00:00Z',
    summary: [
        'Root cause for Confused checkout: 212 sessions answered yes vs 1,340 answered no, last 30 days',
        '',
        '**TL;DR:** Two causes explain 61% of flagged sessions: the shipping options reset after an address edit (38%), and a coupon error rendered below the fold on mobile (23%).',
        '',
        '## Shipping options reset after an address edit',
        '',
        '- 81 sessions, 38% of the bucket, 4% of the contrast.',
    ].join('\n'),
}

const rootCauseMocks = mswDecorator({
    get: {
        '/api/projects/:team_id/signals/scout/configs/': [rootCauseScoutConfig],
        '/api/projects/:team_id/vision/scanners/:scannerId/scout_reports/': [rootCauseReport],
    },
})

// A scanner with a root cause scout no longer gets the offer; its reports show in the scout card.
export const MonitorOverviewWithRootCause: StoryObj = {
    parameters: { pageUrl: urls.replayVision(monitorOverviewScanner.id) },
    decorators: [overviewDecorator(monitorOverviewScanner, monitorOverviewStats), rootCauseMocks],
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

export const ScannerEditorTriggers: StoryObj = {
    parameters: { pageUrl: urls.replayVisionScannerTriggers(summarizerScanner.id) },
}

// The experiment shows as the first condition of the filters, so a scanner with no filters of its own
// does not read as scanning every recording.
export const ScannerEditorTriggersExperiment: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerTriggers(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [variantsDecorator(variantsReadout())],
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

// The monitor allows inconclusive answers, and this one ran out of recording before the user decided.
const inconclusiveObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000d9',
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            confidence: 0.58,
            verdict: 'inconclusive',
            reasoning:
                'The user added two items to the cart and opened the payment step, where the card fields are masked. The recording ends about ten seconds later with the page still loading, so it does not show whether the payment went through or whether the user gave up. There is no retry, error message or backtracking before the recording stops.',
        },
        signals_count: 0,
    },
})

export const ObservationDetailMonitorInconclusive: StoryObj = observationDetailStory(inconclusiveObservationDetail)

// The Session Replay "Summarize" button mints an inline scanner with the session summary template's prompt, so
// its observations carry that template's written question.
const summarizeButtonObservationDetail = observation({
    id: '00000000-0000-0000-0000-0000000000da',
    scanner_id: '00000000-0000-0000-0000-00000000001a',
    scanner_origin: 'inline',
    recording_subject_email: 'bob@example.com',
    distinct_id: 'user_2m1x9d',
    prompt_question: 'What did the user do in this session?',
    scanner_snapshot: {
        ...observation().scanner_snapshot!,
        name: '',
        scanner_config: {
            prompt: "Summarize what the user did in this session: which pages they visited, what they tried to accomplish, and any notable moments like errors, confusion, or successful completions. Be concrete and don't speculate.",
            length: 'medium',
        },
    },
})

export const ObservationDetailSummarizeButton: StoryObj = observationDetailStory(summarizeButtonObservationDetail)

// A one-off scan asked through PostHog AI or MCP: an inline scanner with its own prompt and no written question.
const inlineScanObservationDetail = observation({
    ...monitorObservationDetail,
    id: '00000000-0000-0000-0000-0000000000db',
    scanner_id: '00000000-0000-0000-0000-00000000001b',
    scanner_origin: 'inline',
    prompt_question: null,
    previous_observation_id: null,
    next_observation_id: null,
    scanner_snapshot: {
        ...monitorObservationDetail.scanner_snapshot!,
        name: '',
        scanner_config: { prompt: 'Did the user open the pricing page and leave without upgrading?' },
    },
    scanner_result: {
        model_output: {
            scanner_type: 'monitor',
            confidence: 0.9,
            verdict: 'yes',
            reasoning:
                'The user opened the pricing page twice, expanded the plan comparison, and left the app from there both times without starting a checkout.',
        },
        signals_count: 0,
    },
})

export const ObservationDetailInlineScan: StoryObj = observationDetailStory(inlineScanObservationDetail)

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

// The goal-based creation flow when the flag's test variant is on: a typed goal and budget on the
// left, one-click starting points on the right.
export const ScannerEditorGoalFlow: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionScannerTemplate('new'),
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_FLOW_V2]: 'test' },
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
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_FLOW_V2]: 'test' },
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
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_FLOW_V2]: 'test' },
    },
    decorators: [
        mswDecorator({
            get: {
                // The targeting card and the snack read the experiment's name from this fetch.
                '/api/projects/:team_id/experiments/:id/': {
                    id: 11,
                    name: 'AI-based scanner creation',
                    description: 'Does the goal flow beat the template gallery?',
                    feature_flag_key: 'ai-scanner-creation-flow',
                    feature_flag: {
                        id: 11,
                        key: 'ai-scanner-creation-flow',
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
        featureFlags: { [FEATURE_FLAGS.VISION_GOAL_FLOW_V2]: 'test' },
        testOptions: { waitForLoadersToDisappear: false, waitForSelector: '.LemonSkeleton' },
    },
    decorators: [
        // A draft request that never answers, because a failed one sends the page back to the goal step.
        mswDecorator({
            post: {
                '/api/projects/:team_id/vision/scanners/draft/': (): Promise<never> => new Promise(() => {}),
            },
        }),
        (StoryFn) => {
            const logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            // Hold the draft loader open so the overview renders its skeleton instead of a result.
            logic.actions.draftScannerFromGoal('find out where people give up in billing', 5000)
            return <StoryFn />
        },
    ],
}

// A summary that carries chapters, so the result card gains Summary and Timeline tabs.
const timelineObservationDetail = (() => {
    const withChapters = timelineSummary({ chapters: LONG, inactive: LONG_INACTIVE })
    const output = withChapters.scanner_result!.model_output as Record<string, unknown>
    return observation({
        ...observationDetail,
        id: '00000000-0000-0000-0000-0000000000d9',
        scanner_result: {
            ...observationDetail.scanner_result!,
            model_output: {
                ...(observationDetail.scanner_result!.model_output as Record<string, unknown>),
                chapters: output.chapters,
                inactive_periods: output.inactive_periods,
            },
        } as ReplayObservationApi['scanner_result'],
        media: withChapters.media,
    })
})()

export const ObservationDetailSummaryWithTimeline: StoryObj = observationDetailStory(timelineObservationDetail)

// The timeline tab on an hour-long recording, the only story where the rail scrolls inside the card.
export const ObservationDetailTimeline: StoryObj = {
    ...observationDetailStory(timelineObservationDetail),
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Timeline'))
        await within(canvasElement).findByText('Session start')
    },
}

export const ExperimentVariants: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [variantsDecorator(variantsReadout())],
}

// No variant analysis scout yet: the counts show, and the comparison offers to set one up.
export const ExperimentVariantsNoScout: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [variantsDecorator(withoutAnalysis(variantsReadout({ analysis: null })))],
}

export const ExperimentVariantsFirstRunPending: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [
        variantsDecorator(withoutAnalysis(variantsReadout({ analysis: { ...readyAnalysis, recorded_at: null } }))),
    ],
}

// Before the first observation: each variant shows where its themes and observations will go.
export const ExperimentVariantsWaitingForObservations: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [
        variantsDecorator(
            withoutAnalysis(
                variantsReadout({
                    analysis: { ...readyAnalysis, recorded_at: null },
                    window: { total_observations: 0, first_observation_at: null, last_observation_at: null },
                    unattributed_count: 0,
                    variants: variantsReadout().variants.map((variant) => ({
                        ...variant,
                        observations: 0,
                        distinct_people: 0,
                        median_session_duration_s: null,
                        sampling_rate: null,
                        latest_observations: [],
                    })),
                })
            )
        ),
    ],
}

export const ExperimentVariantsThreeVariants: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
    },
    decorators: [
        variantsDecorator(
            variantsReadout({
                window: { ...variantsReadout().window, total_observations: 99 },
                variants: [
                    ...variantsReadout().variants,
                    {
                        ...variantsReadout().variants[1],
                        key: 'test-compact',
                        observations: 28,
                        distinct_people: 27,
                        sampling_rate: 0.45,
                        digest: null,
                        latest_observations: [],
                    },
                ],
            })
        ),
    ],
}

// About 520px of scene, the width a laptop leaves with the side panel open. The nav collapses at
// this viewport, so the scene takes the whole window less its padding.
export const ExperimentVariantsNarrow: StoryObj = {
    parameters: {
        pageUrl: urls.replayVision(experimentScanner.id),
        featureFlags: { [FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]: true },
        testOptions: { viewport: { width: 560, height: 1800 } },
    },
    decorators: [variantsDecorator(variantsReadout())],
}
