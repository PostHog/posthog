import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { RecordingsQuery } from '~/queries/schema/schema-general'
import { StartupProgramLabel } from '~/types'

import type {
    DraftScannerResponseApi,
    ObservationStatsApi,
    ReplayObservationApi,
    ReplayScannerApi,
    ReplayScannerPromptSuggestionApi,
    ScannerStatsResponseApi,
    UserBasicApi,
    VisionActionApi,
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
        model: 'gemini-3.7-flash',
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
        user_access_level: 'editor',
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
    period_start: '2026-05-01T00:00:00Z',
    period_end: '2026-06-01T00:00:00Z',
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

const scannerImpact = {
    affected_sessions: 1284,
    affected_users: 967,
    sessions_without_user: 41,
    window_days: 30,
}

const observation = (overrides: Partial<ReplayObservationApi> = {}): ReplayObservationApi =>
    ({
        id: '00000000-0000-0000-0000-0000000000b1',
        scanner_id: summarizerScanner.id,
        session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d07',
        status: 'succeeded',
        error_reason: '',
        workflow_id: 'vision-observation-1',
        scanner_snapshot: {
            name: summarizerScanner.name,
            scanner_type: 'summarizer',
            scanner_version: 1,
            model: 'gemini-3.7-flash',
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
        triggered_by: 'schedule',
        triggered_by_user: null,
        distinct_id: 'user_8f3k2j',
        recording_subject_email: 'alice@example.com',
        previous_observation_id: null,
        next_observation_id: null,
        label: null,
        started_at: '2026-05-11T09:00:00Z',
        completed_at: '2026-05-11T09:01:00Z',
        created_at: '2026-05-11T09:00:00Z',
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
        }),
        observation({
            id: '00000000-0000-0000-0000-0000000000b4',
            session_id: '01966b3f-70a1-7c52-a4d5-3f9b2e8c1d10',
            recording_subject_email: 'bob@example.com',
            distinct_id: 'user_2m1x9d',
            label: { is_correct: false, feedback: 'Missed the failed payment retry entirely.' },
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
    },
})

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

const digestAction: VisionActionApi = {
    id: '00000000-0000-0000-0000-0000000000f1',
    name: 'Daily checkout digest',
    scanner: summarizerScanner.id,
    enabled: true,
    is_scanner_digest: true,
    trigger_type: 'schedule',
    mode: 'group_summary',
    trigger_config: { rrule: 'FREQ=DAILY;BYHOUR=9;BYMINUTE=0', timezone: 'UTC' },
    selection: {},
    synthesis_config: { prompt_guide: 'Lead with the most common friction point.' },
    delivery_config: [{ type: 'webhook', url: 'https://hooks.example.com/replay-vision' }],
    next_run_at: '2026-05-13T09:00:00Z',
    last_run_at: '2026-05-12T09:00:00Z',
    hog_flow_id: null,
    created_at: '2026-05-01T00:00:00Z',
    created_by: alice,
    updated_at: '2026-05-01T00:00:00Z',
} as VisionActionApi

const alertAction: VisionActionApi = {
    ...digestAction,
    id: '00000000-0000-0000-0000-0000000000f2',
    name: 'Coupon friction alert',
    is_scanner_digest: false,
    mode: 'alert',
    alert_config: { frequency: 'on_breach', metric: 'count', threshold: 10, direction: 'above', window_days: 1 },
    created_by: bob,
} as VisionActionApi

const actions = { count: 2, next: null, previous: null, results: [digestAction, alertAction] }

const completedRun = {
    id: '00000000-0000-0000-0000-0000000000a1',
    status: 'completed',
    scheduled_at: '2026-05-12T09:00:00Z',
    observation_count: 12,
    error_reason: null,
    is_recovery: false,
    created_at: '2026-05-12T09:00:05Z',
    updated_at: '2026-05-12T09:01:10Z',
}

const actionRuns = {
    count: 2,
    next: null,
    previous: null,
    results: [
        completedRun,
        {
            ...completedRun,
            id: '00000000-0000-0000-0000-0000000000a2',
            status: 'skipped',
            scheduled_at: '2026-05-11T09:00:00Z',
            observation_count: 0,
            error_reason: 'No new observations in the window.',
        },
    ],
}

const actionRunDetail = {
    ...completedRun,
    synthesized_markdown:
        '## Checkout friction, May 12\n\nCoupon validation failures dominated today [1][2]. Two sessions abandoned the cart after payment retries [3].',
    observations: [
        {
            index: 1,
            id: observations.results[0].id,
            session_id: observations.results[0].session_id,
            recording_subject_email: 'alice@example.com',
            title: 'Checkout hesitation after coupon',
            created_at: '2026-05-11T09:00:00Z',
        },
        {
            index: 2,
            id: observations.results[1].id,
            session_id: observations.results[1].session_id,
            recording_subject_email: 'very.long.customer.email.address@enterprise-customer-company-name.example.com',
            title: 'Coupon validation loop at checkout',
            created_at: '2026-05-11T10:00:00Z',
        },
        {
            index: 3,
            id: observations.results[3].id,
            session_id: observations.results[3].session_id,
            recording_subject_email: 'bob@example.com',
            title: 'Cart abandoned after payment retry',
            created_at: '2026-05-11T11:00:00Z',
        },
    ],
}

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
                '/api/projects/:team_id/vision/quota/': quota,
                '/api/projects/:team_id/vision/scanners/:id/': summarizerScanner,
                '/api/projects/:team_id/vision/scanners/:id/impact/': scannerImpact,
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
                '/api/projects/:team_id/vision/actions/': actions,
                '/api/projects/:team_id/vision/actions/:id/': digestAction,
                '/api/projects/:team_id/vision/actions/:visionActionId/runs/': actionRuns,
                '/api/projects/:team_id/vision/actions/:visionActionId/runs/:id/': actionRunDetail,
                '/api/projects/:team_id/vision/observations/:id/': observationDetail,
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': observationsTrend,
                '/api/projects/:team_id/vision/scanners/estimate/': estimate,
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

// Nothing else renders the summarizer's friction/keyword panels, so this story is what catches regressions there.
export const SummarizerOverview: StoryObj = {
    parameters: { pageUrl: urls.replayVision(summarizerScanner.id) },
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
                    summarizer: null,
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
                                model: 'gemini-3.7-flash',
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

export const ScannerOnDemand: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=on-demand` },
}

export const ScannerConfiguration: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=configuration` },
}

// Test arms of the model tier-naming experiment: models labeled by capability tier instead of
// provider names.
export const ScannerConfigurationTierNames: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=configuration`,
        featureFlags: { [FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT]: 'test' },
    },
}

export const ScannerConfigurationLiteStandardPro: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=configuration`,
        featureFlags: {
            [FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT]: 'lite-standard-pro',
        },
    },
}

// Renders the pending recommendation's diff and change cards plus the rating list.
export const ScannerCalibration: StoryObj = {
    parameters: { pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=calibration` },
}

export const ScannerDigests: StoryObj = {
    parameters: {
        pageUrl: `${urls.replayVision(summarizerScanner.id)}?tab=actions`,
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

export const ActionEditorAlert: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionActionNew(summarizerScanner.id, 'alert'),
    },
}

// Editing the digest exercises the schedule section (weekday pills, time controls).
export const ActionEditorDigest: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionActionEdit(digestAction.id),
    },
}

export const ActionDetail: StoryObj = {
    parameters: {
        pageUrl: urls.replayVisionAction(digestAction.id),
    },
}

export const ObservationDetail: StoryObj = {
    parameters: { pageUrl: urls.replayVisionObservation(observationDetail.id) },
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

// The goal-based creation flow's two questions replace the template gallery when the flag's test
// variant is on.
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
