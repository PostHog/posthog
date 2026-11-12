import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { BREAKDOWN_NULL_STRING_LABEL } from 'scenes/insights/utils'

import { type ExperimentExposureQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { userEvent } from 'storybook/test'

import type {
    ExperimentHealthCheckResultApi,
    ExperimentHealthCheckRuleApi,
    ExperimentHealthSetupApi,
} from '../generated/api.schemas'
import { HealthChecksPanel } from './HealthChecksPanel'
import type { HealthPanelCheck } from './healthPanelChecks'
import type { HealthPanelFinding } from './healthPanelFindings'

const DESCRIPTIONS: Partial<Record<HealthPanelCheck['key'], string>> = {
    flag_state:
        "Checks that the feature flag matches the experiment's status. A running experiment needs a flag that is on and serves every variant, or new users stop entering it. Before launch and after the end, a flag that serves variants shows them to users that the results don't count.",
    split_changed_mid_run:
        'Looks for changes to the variant split after users were first exposed. A change can move users who already saw one variant to another, which mixes their behavior across variants and biases the results.',
    no_metric:
        'Checks that a launched experiment has at least one metric. Without a metric, the experiment counts exposures but has nothing to compare the variants on.',
    srm: 'Tests whether exposed users are divided across variants in the percentages of the variant split. A mismatch usually means that a variant override, the assignment or the tracking adds or loses users in one variant, which can bias the results.',
    multiple_variants_share:
        'Counts the users exposed to more than one variant, which the results leave out. A high share usually means that one person has several IDs, and the variants can then lose different users, which biases the results.',
}

const description = (key: HealthPanelCheck['key']): string =>
    DESCRIPTIONS[key] ?? 'Looks for a problem in the setup of the experiment that can make its results wrong.'

const passed = (key: HealthPanelCheck['key'], name: string): ExperimentHealthCheckResultApi => ({
    key,
    name,
    description: description(key),
    status: 'passed',
    reason: null,
    values: {},
    rule: null,
    rows: [],
})

const skipped = (
    key: HealthPanelCheck['key'],
    name: string,
    status: 'not_applicable' | 'not_checked',
    reason: string
): ExperimentHealthCheckResultApi => ({
    key,
    name,
    description: description(key),
    status,
    reason,
    values: {},
    rule: null,
    rows: [],
})

const FLAG_SETUP_CHECKS = [
    passed('flag_state', "Flag state that doesn't match the experiment"),
    passed('flag_variants_mismatch', 'Flag variants not set up'),
    passed('forced_variant_release_condition', 'Release conditions that force a variant'),
]

const SETUP: ExperimentHealthSetupApi = {
    release_conditions: [{ rollout_percentage: 50, property_count: 1, aggregation_group_type_index: null }],
    early_exit: false,
    bucketing_identifier: 'distinct_id',
    aggregation_group_type_index: null,
    evaluation_runtime: 'all',
    evaluation_contexts: ['web-app'],
    ensure_experience_continuity: false,
}

const meta: Meta<typeof HealthChecksPanel> = {
    title: 'Experiments/HealthChecksPanel',
    component: HealthChecksPanel,
    parameters: {
        layout: 'centered',
        mockDate: '2026-11-03 12:00:00',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
    args: { onFindingActedOn: () => {}, exposures: null, setup: SETUP },
    decorators: [
        (Story) => (
            <div className="w-[60rem]">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof HealthChecksPanel>

export const Draft: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped(
                'split_changed_mid_run',
                'Variant split changes since launch',
                'not_applicable',
                'Runs after launch'
            ),
            skipped('no_metric', 'Metrics not set up', 'not_applicable', 'Runs after launch'),
        ],
        findings: [
            {
                code: 'new_flag_no_traffic',
                subcode: null,
                reason: null,
                severity: 'info',
                title: 'The feature flag has no traffic yet',
                detail: "PostHog hasn't recorded any calls to the linked feature flag yet. The experiment only counts users after your code evaluates the flag, so launch after the flag starts getting traffic. New calls can take up to an hour to show up here.",
                evidence: {},
                actions: [],
            },
        ],
        isDraft: true,
        exposureChecksMissing: false,
    },
}

const found = (key: HealthPanelCheck['key'], name: string): ExperimentHealthCheckResultApi => ({
    key,
    name,
    description: description(key),
    status: 'finding',
    reason: null,
    values: {},
    rule: null,
    rows: [],
})

export const ChecksThatCouldNotRun: Story = {
    args: {
        checks: [
            ...FLAG_SETUP_CHECKS,
            skipped(
                'split_changed_mid_run',
                'Variant split changes since launch',
                'not_checked',
                "Couldn't check because you can't view the linked feature flag's history"
            ),
            passed('no_metric', 'Metrics not set up'),
        ],
        findings: [],
        isDraft: false,
        exposureChecksMissing: true,
    },
}

const SRM_RULE: ExperimentHealthCheckRuleApi = {
    value: 'p_value',
    threshold: 0.001,
    warns: 'below',
    test: 'chi_squared',
    minimum: { value: 'compared_count', threshold: 100 },
}

const BIAS_RULE: ExperimentHealthCheckRuleApi = {
    value: 'multiple_variant_percentage',
    threshold: 0.1,
    warns: 'above',
    test: null,
    minimum: { value: 'multiple_variant_count', threshold: 5 },
}

const MULTIPLE_VARIANTS_RULE: ExperimentHealthCheckRuleApi = { ...BIAS_RULE, threshold: 5 }

const UNEVEN_SPLIT_EXPOSURES: ExperimentExposureQueryResponse = {
    kind: NodeKind.ExperimentExposureQuery,
    timeseries: [],
    total_exposures: { control: 4790, test: 2420, 'test-2': 2392, $multiple: 403 },
    exposed_by_library: { web: 8204, 'posthog-node': 1601, [BREAKDOWN_NULL_STRING_LABEL]: 200 },
    date_range: { date_from: '2026-10-19T00:00:00Z' },
    sample_ratio_mismatch: { expected: { control: 4801, test: 2400.5, 'test-2': 2400.5 }, p_value: 0.71 },
    health_checks: [
        { key: 'srm', name: 'Split of users across variants', status: 'passed', reason: null },
        { key: 'bias_risk_multiple_excluded', name: 'Bias from an uneven split', status: 'finding', reason: null },
        { key: 'multiple_variants_share', name: 'Users exposed to multiple variants', status: 'passed', reason: null },
    ],
    last_refresh: '2026-11-03T10:00:00Z',
} as ExperimentExposureQueryResponse

const MULTIPLE_VALUES = {
    exposed_count: 10005,
    multiple_variant_count: 403,
    multiple_variant_percentage: 4.03,
    multiple_variant_handling: 'exclude',
}

const READ_CHECKS: HealthPanelCheck[] = [
    {
        ...passed('flag_state', "Flag state that doesn't match the experiment"),
        values: { flag_active: true, flag_deleted: false, flag_rolled_out: true, shipped_variant: null },
    },
    passed('flag_variants_mismatch', 'Flag variants not set up'),
    {
        ...passed('metric_calculation_failed', 'Failed metric calculations'),
        values: {
            metric_count: 3,
            completed_metric_count: 3,
            failed_metric_count: 0,
            calculated_at: '2026-11-03T08:00:00Z',
        },
    },
    {
        ...passed('zero_exposures', 'Exposures not received since launch'),
        values: { exposed_count: 10005, since_launch_hours: 348 },
        rule: {
            value: 'exposed_count',
            threshold: 1,
            warns: 'below',
            test: null,
            minimum: { value: 'since_launch_hours', threshold: 24 },
        },
    },
    {
        ...passed('srm', 'Split of users across variants'),
        values: { p_value: 0.71, compared_count: 9602, multiple_variant_count: 403 },
        rule: SRM_RULE,
    },
    {
        ...passed('multiple_variants_share', 'Users exposed to multiple variants'),
        values: MULTIPLE_VALUES,
        rule: MULTIPLE_VARIANTS_RULE,
    },
    {
        ...skipped(
            'metrics_not_matured',
            'Metric windows not complete yet',
            'not_applicable',
            'Runs when "Require completed conversion or retention window" is on'
        ),
        values: { only_count_matured_users: false },
    },
]

const BIAS_FINDING: HealthPanelFinding = {
    code: 'bias_risk_multiple_excluded',
    subcode: null,
    reason: null,
    severity: 'warning',
    title: 'The uneven split may bias the results',
    detail: '4.0% of users were exposed to multiple variants. With an uneven variant split and the Exclude handling, these users were dropped more often from the smaller variant, so its metrics can be biased. Use an even split and control exposure with the overall rollout, or switch the handling to First seen.',
    evidence: { multiple_variant_percentage: 4.03 },
    actions: ['adjust_distribution', 'use_first_seen_variant'],
    check: 'bias_risk_multiple_excluded',
}

export const RunningWithAnIssue: Story = {
    args: {
        checks: [
            ...READ_CHECKS,
            {
                ...found('bias_risk_multiple_excluded', 'Bias from an uneven split'),
                values: MULTIPLE_VALUES,
                rule: BIAS_RULE,
            },
        ],
        findings: [BIAS_FINDING],
        exposures: UNEVEN_SPLIT_EXPOSURES,
        isDraft: false,
        exposureChecksMissing: false,
    },
}

export const IssueDetails: Story = {
    args: RunningWithAnIssue.args,
    play: async ({ canvasElement }) => {
        await userEvent.click(
            await within(canvasElement).findByRole('button', { name: /The uneven split may bias the results/ })
        )
    },
}

export const CheckDetailsWithWhatItRead: Story = {
    args: {
        checks: READ_CHECKS,
        findings: [],
        exposures: UNEVEN_SPLIT_EXPOSURES,
        isDraft: false,
        exposureChecksMissing: false,
    },
    play: async ({ canvasElement }) => {
        await userEvent.click(
            await within(canvasElement).findByRole('button', { name: /Split of users across variants/ })
        )
    },
}

export const NarrowWithAnIssue: Story = {
    args: RunningWithAnIssue.args,
    decorators: [
        (Story) => (
            <div className="w-[32rem]">
                <Story />
            </div>
        ),
    ],
    play: async ({ canvasElement }) => {
        await userEvent.click(
            await within(canvasElement).findByRole('button', { name: /The uneven split may bias the results/ })
        )
    },
}

const CHECKS_WITH_ROWS: HealthPanelCheck[] = [
    ...READ_CHECKS,
    {
        ...passed('early_significance', 'Significance on a small sample'),
        values: { metric_name: 'Checkout completed', sample_count: 9602, planned_sample_count: 14800 },
        rows: [
            { variant: 'test', difference_percentage: 14.2, detectable_difference_percentage: 9.8, significant: true },
            {
                variant: 'test-2',
                difference_percentage: 3.1,
                detectable_difference_percentage: 9.9,
                significant: false,
            },
        ],
    },
    {
        ...passed('forced_variant_release_condition', 'Release conditions that force a variant'),
        values: {
            forced_condition_count: 1,
            matched_count: 4277,
            traffic_since_at: '2026-10-27T12:00:00Z',
            flag_service_call_percentage: 92.4,
        },
        rows: [
            { variant: 'control', variant_matched_count: 2140, forced_count: 0, forced_percentage: 0 },
            { variant: 'test', variant_matched_count: 1075, forced_count: 9, forced_percentage: 0.84 },
            { variant: 'test-2', variant_matched_count: 1062, forced_count: 0, forced_percentage: 0 },
        ],
    },
    {
        ...passed('release_conditions_changed_mid_run', 'Release condition changes since launch'),
        rows: [
            {
                changed_at: '2026-10-19T07:05:00Z',
                before: 'Set 1: 100%, filters on email, forces "test"\nSet 2: 50%',
                after: 'Set 1: 100%, filters on email, forces "test"\nSet 2: 100%',
                before_exposure: true,
            },
            {
                changed_at: '2026-10-24T12:10:00Z',
                before: 'Set 1: 100%, filters on email, forces "test"\nSet 2: 100%',
                after: 'Set 1: 100%, filters on email\nSet 2: 100%',
                before_exposure: false,
            },
        ],
    },
    {
        ...passed('stale_experiment', 'Experiment running past 60 days'),
        values: { since_start_hours: 363, daily_calculation_ends_at: '2026-12-18T09:00:00Z' },
        rule: { value: 'since_start_hours', threshold: 1440, warns: 'above', test: null, minimum: null },
    },
    {
        ...skipped(
            'metric_all_zero',
            'Metrics at zero in every variant',
            'not_applicable',
            'Runs once a primary metric at 0 has 1,000 users and 72 hours of data'
        ),
        rows: [
            {
                metric_name: 'Checkout completed',
                metric_role: 'primary',
                ratio_side: null,
                sample_count: 412,
                data_hours: 31,
            },
        ],
    },
]

export const PassedCheckDetailsWithRows: Story = {
    args: {
        checks: CHECKS_WITH_ROWS,
        findings: [],
        exposures: UNEVEN_SPLIT_EXPOSURES,
        isDraft: false,
        exposureChecksMissing: false,
    },
    play: async ({ canvasElement }) => {
        await userEvent.click(
            await within(canvasElement).findByRole('button', { name: /Significance on a small sample/ })
        )
    },
}

export const FlagChangeDetails: Story = {
    args: PassedCheckDetailsWithRows.args,
    play: async ({ canvasElement }) => {
        await userEvent.click(
            await within(canvasElement).findByRole('button', { name: /Release condition changes since launch/ })
        )
    },
}
