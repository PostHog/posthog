import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import EXPERIMENT_DRAFT from '~/mocks/fixtures/api/experiments/_experiment_draft.json'
import { toPaginatedResponse } from '~/mocks/handlers'

import type { ExperimentSetupContextResponseApi } from 'products/experiments/frontend/generated/api.schemas'

const SETUP_CONTEXT_PATH = '/api/projects/:team_id/experiments/setup_context/'
const COMPUTED_AT = '2025-01-27T09:00:00Z'

// Typed as the generated response so a new required field on the serializer breaks the typecheck here.
const FULL_CONTEXT: ExperimentSetupContextResponseApi = {
    team_defaults: {
        status: 'ok',
        data: {
            stats_method: null,
            confidence_level: null,
            minimum_detectable_effect: 20,
            product_default_minimum_detectable_effect: 30,
            product_default_stats_method: 'bayesian',
            product_default_confidence_level: 0.95,
            only_count_matured_users: false,
            cuped_enabled: true,
            sequential_testing_enabled: false,
            flags_persistence_default: false,
            test_account_filter_count: 2,
            new_experiments_filter_test_accounts: true,
            default_exposure_event: '$feature_flag_called',
        },
    },
    sdk_profile: {
        status: 'ok',
        data: {
            window_days: 7,
            source_event: '$feature_flag_called',
            computed_at: COMPUTED_AT,
            libs: [
                {
                    lib: 'web',
                    category: 'web',
                    calls: 184_220,
                    distinct_ids: 41_380,
                    device_id_share: 1,
                    locally_evaluated_share: null,
                    anonymous_share: 0.42,
                },
                {
                    lib: 'posthog-node',
                    category: 'server',
                    calls: 96_410,
                    distinct_ids: 12_905,
                    device_id_share: 0,
                    locally_evaluated_share: 0.97,
                    anonymous_share: null,
                },
            ],
            libs_truncated: false,
            flags_seen: 14,
            flags_evaluated_on_server_and_web: 3,
            evaluated_on_server_and_web: true,
            libs_on_any_event: null,
            libs_on_any_event_truncated: false,
        },
    },
    target_surface: {
        status: 'ok',
        data: {
            window_days: 14,
            source_event: '$pageview',
            target_url_contains: '/pricing',
            target_properties: [{ key: '$host', type: 'event', operator: 'exact', value: ['app.example.com'] }],
            computed_at: COMPUTED_AT,
            test_accounts_filtered: true,
            unique_persons: 8_470,
            exposures_per_day_estimate: 605,
            libs: [{ lib: 'web', category: 'web', unique_persons: 8_470, anonymous_share: 0.38, device_id_share: 1 }],
            libs_truncated: false,
            anonymous_share: 0.38,
            device_id_share: 1,
        },
    },
    candidate_metric: {
        status: 'ok',
        data: {
            window_days: 14,
            source_event: 'signed_up',
            metric_properties: [],
            target_event: '$pageview',
            computed_at: COMPUTED_AT,
            test_accounts_filtered: true,
            persons_reached: 8_470,
            persons_converted: 593,
            conversion_rate: 0.07,
            funnel_baseline_stats: { number_of_samples: 8_470, sum: 593, step_counts: [593] },
            mean_count_baseline_stats: { number_of_samples: 8_470, sum: 640, sum_squares: 731 },
            note: 'Metric events are counted in the whole window, not only after the first target event.',
            event_volume: 1_204,
            unique_persons: 1_130,
        },
    },
    previous_experiments: {
        status: 'ok',
        data: {
            experiments: [
                {
                    id: 101,
                    name: 'Pricing page layout',
                    state: 'running',
                    created_at: '2025-01-10T10:00:00Z',
                    start_date: '2025-01-12T10:00:00Z',
                    end_date: null,
                    conclusion: null,
                    feature_flag_key: 'pricing-page-layout',
                    variant_count: 2,
                    split_even: true,
                    serving_single_variant: null,
                    rollout_percentage: 100,
                    multiple_variant_handling: 'exclude',
                    multiple_variant_handling_set: false,
                    ensure_experience_continuity: true,
                    bucketing_identifier: 'distinct_id',
                    evaluation_runtime: 'all',
                    group_aggregation: false,
                    custom_exposure_event: null,
                    custom_exposure_action_id: null,
                    exposure_property_filters: [{ key: '$pathname', type: 'event', value: ['/pricing'] }],
                    activation_event: null,
                    activation_action_id: null,
                    filter_test_accounts: true,
                    primary_metric_count: 1,
                    secondary_metric_count: 2,
                    shared_metric_count: 1,
                    primary_metric_types: ['funnel'],
                    primary_metric_events: ['signed_up'],
                    primary_metric_action_ids: [],
                    minimum_detectable_effect: 20,
                    stats_method: 'bayesian',
                    has_holdout: false,
                    outcome: {
                        metric_type: 'funnel',
                        metric_samples: 6_120,
                        analyzed_exposures: 6_120,
                        control_baseline_value: 0.068,
                        any_variant_significant: false,
                        result_completed_at: '2025-01-27T06:00:00Z',
                        result_data_through: '2025-01-27T00:00:00Z',
                    },
                },
                {
                    id: 97,
                    name: 'Onboarding checklist',
                    state: 'stopped',
                    created_at: '2024-12-02T10:00:00Z',
                    start_date: '2024-12-03T10:00:00Z',
                    end_date: '2025-01-05T10:00:00Z',
                    conclusion: 'won',
                    feature_flag_key: 'onboarding-checklist',
                    variant_count: 2,
                    split_even: null,
                    serving_single_variant: 'test',
                    rollout_percentage: 100,
                    multiple_variant_handling: 'first_seen',
                    multiple_variant_handling_set: true,
                    ensure_experience_continuity: false,
                    bucketing_identifier: 'device_id',
                    evaluation_runtime: 'client',
                    group_aggregation: false,
                    custom_exposure_event: 'onboarding_viewed',
                    custom_exposure_action_id: null,
                    exposure_property_filters: [],
                    activation_event: null,
                    activation_action_id: null,
                    filter_test_accounts: true,
                    primary_metric_count: 1,
                    secondary_metric_count: 0,
                    shared_metric_count: 0,
                    primary_metric_types: ['retention'],
                    primary_metric_events: ['onboarding_viewed', 'project_created'],
                    primary_metric_action_ids: [],
                    minimum_detectable_effect: null,
                    stats_method: 'frequentist',
                    has_holdout: true,
                    outcome: {
                        metric_type: 'retention',
                        metric_samples: 2_310,
                        analyzed_exposures: null,
                        control_baseline_value: null,
                        any_variant_significant: true,
                        result_completed_at: '2025-01-05T11:00:00Z',
                        result_data_through: '2025-01-05T10:00:00Z',
                    },
                },
                {
                    id: 104,
                    name: 'Shorter signup form',
                    state: 'draft',
                    created_at: '2025-01-25T10:00:00Z',
                    start_date: null,
                    end_date: null,
                    conclusion: null,
                    feature_flag_key: 'shorter-signup-form',
                    variant_count: 3,
                    split_even: false,
                    serving_single_variant: null,
                    rollout_percentage: 50,
                    multiple_variant_handling: 'exclude',
                    multiple_variant_handling_set: false,
                    ensure_experience_continuity: false,
                    bucketing_identifier: 'distinct_id',
                    evaluation_runtime: 'all',
                    group_aggregation: false,
                    custom_exposure_event: null,
                    custom_exposure_action_id: null,
                    exposure_property_filters: [],
                    activation_event: 'signup_form_focused',
                    activation_action_id: null,
                    filter_test_accounts: false,
                    primary_metric_count: 0,
                    secondary_metric_count: 0,
                    shared_metric_count: 0,
                    primary_metric_types: [],
                    primary_metric_events: [],
                    primary_metric_action_ids: [],
                    minimum_detectable_effect: null,
                    stats_method: 'bayesian',
                    has_holdout: false,
                    outcome: null,
                },
            ],
            summary: {
                total: 3,
                launched: 2,
                launched_without_results: 0,
                launched_with_unknown_analyzed_exposures: 1,
                launched_with_zero_analyzed_exposures: 0,
                launched_with_under_100_analyzed_exposures: 0,
                using_device_id_bucketing: 1,
                using_persistence: 1,
                using_custom_exposure: 1,
                using_exposure_property_filters: 1,
                using_activation: 1,
                using_uneven_split: 1,
                serving_single_variant: 1,
            },
        },
    },
    shared_metrics: {
        status: 'ok',
        data: {
            metric_event: 'signed_up',
            metric_event_match_truncated: false,
            metrics: [
                {
                    id: 12,
                    name: 'Signup conversion',
                    metric_type: 'funnel',
                    events: ['$pageview', 'signed_up'],
                    action_ids: [],
                    used_as_primary: 4,
                    used_as_secondary: 1,
                    last_used_at: '2025-01-12T10:00:00Z',
                    matches_metric_event: true,
                    metric_event_roles: ['funnel_final_step'],
                },
                {
                    id: 15,
                    name: 'Seven day retention',
                    metric_type: 'retention',
                    events: ['signed_up', 'project_created'],
                    action_ids: [],
                    used_as_primary: 1,
                    used_as_secondary: 3,
                    last_used_at: '2024-12-03T10:00:00Z',
                    matches_metric_event: true,
                    metric_event_roles: ['retention_start'],
                },
                {
                    id: 9,
                    name: 'Revenue per user',
                    metric_type: 'mean',
                    events: [],
                    action_ids: [31],
                    used_as_primary: 0,
                    used_as_secondary: 2,
                    last_used_at: null,
                    matches_metric_event: false,
                    metric_event_roles: [],
                },
            ],
        },
    },
}

// What a project with no flag calls and no inputs gets back, with one read that timed out and one
// that failed, so every section status renders in one screenshot.
const DEGRADED_CONTEXT: ExperimentSetupContextResponseApi = {
    ...FULL_CONTEXT,
    sdk_profile: { status: 'timed_out', data: null },
    target_surface: { status: 'skipped', data: null },
    candidate_metric: { status: 'skipped', data: null },
    shared_metrics: { status: 'error', data: null },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Experiments/Setup context',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.experiments(),
        featureFlags: [FEATURE_FLAGS.EXPERIMENT_SETUP_CONTEXT],
        testOptions: { viewport: { width: 1300, height: 2400 } },
    },
    decorators: [
        mswDecorator({
            get: {
                // One experiment, because an empty list renders the product empty state without the title actions.
                '/api/projects/:team_id/experiments/': toPaginatedResponse([EXPERIMENT_DRAFT]),
                '/api/projects/:team_id/experiment_holdouts': [],
                '/api/projects/:team_id/experiment_saved_metrics/': [],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

const openTheDrawer: Story['play'] = async ({ canvasElement }) => {
    await userEvent.click(await within(canvasElement).findByText('Setup context'))
    await within(document.body).findByText('Team defaults')
}

export const SetupContextDrawer: Story = {
    decorators: [mswDecorator({ post: { [SETUP_CONTEXT_PATH]: FULL_CONTEXT } })],
    play: openTheDrawer,
}

// Narrow, because the drawer's input grid and the previous experiments table run out of room first.
export const SetupContextDrawerNarrow: Story = {
    parameters: { testOptions: { viewport: { width: 900, height: 2400 } } },
    decorators: [mswDecorator({ post: { [SETUP_CONTEXT_PATH]: FULL_CONTEXT } })],
    play: openTheDrawer,
}

export const SetupContextDrawerDegraded: Story = {
    decorators: [mswDecorator({ post: { [SETUP_CONTEXT_PATH]: DEGRADED_CONTEXT } })],
    play: openTheDrawer,
}
