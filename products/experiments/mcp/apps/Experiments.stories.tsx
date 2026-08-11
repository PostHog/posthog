import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import {
    ExperimentListView,
    type ExperimentData,
    type ExperimentListData,
    ExperimentResultsView,
    type ExperimentResultsData,
    ExperimentView,
} from './index'

const meta: Meta = {
    title: 'MCP Apps/Experiments',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator doesn't have dark mode built-in by default so just disable this to avoid duplicated snapshots
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const runningExperiment: ExperimentData = {
    id: 1,
    name: 'Onboarding flow v2',
    type: 'product',
    description: 'Test whether a simplified onboarding increases activation rates.',
    feature_flag_key: 'onboarding-v2-experiment',
    start_date: '2025-11-01T10:00:00Z',
    created_at: '2025-10-28T09:00:00Z',
    feature_flag: {
        id: 101,
        key: 'onboarding-v2-experiment',
        filters: {
            groups: [{ rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', name: 'Current flow', rollout_percentage: 50 },
                    { key: 'test', name: 'Simplified flow', rollout_percentage: 50 },
                ],
            },
        },
    },
    metrics: [{ kind: 'primary', event: 'user_activated', math: 'total' }],
    _posthogUrl: 'https://us.posthog.com/project/1/experiments/1',
}

const completedExperiment: ExperimentData = {
    id: 2,
    name: 'Pricing page CTA',
    type: 'web',
    description: 'Which CTA copy drives more upgrades?',
    feature_flag_key: 'pricing-cta-test',
    start_date: '2025-09-01T10:00:00Z',
    end_date: '2025-10-01T10:00:00Z',
    created_at: '2025-08-28T09:00:00Z',
    feature_flag: {
        id: 102,
        key: 'pricing-cta-test',
        filters: {
            groups: [{ rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', name: 'Get started', rollout_percentage: 34 },
                    { key: 'test-a', name: 'Start free trial', rollout_percentage: 33 },
                    { key: 'test-b', name: 'Try it now', rollout_percentage: 33 },
                ],
            },
        },
    },
    conclusion: 'significant',
    conclusion_comment: 'test-a outperformed control by 12% on conversion rate.',
    _posthogUrl: 'https://us.posthog.com/project/1/experiments/2',
}

const draftExperiment: ExperimentData = {
    id: 3,
    name: 'Dark mode default',
    description: 'Should new users default to dark mode?',
    feature_flag_key: 'dark-mode-default',
    created_at: '2025-12-01T09:00:00Z',
    feature_flag: {
        id: 103,
        key: 'dark-mode-default',
        filters: {
            groups: [{ rollout_percentage: 100 }],
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 50 },
                    { key: 'test', rollout_percentage: 50 },
                ],
            },
        },
    },
}

export const Running: Story = {
    render: () => <ExperimentView experiment={runningExperiment} />,
    name: 'Running experiment',
}

export const Completed: Story = {
    render: () => <ExperimentView experiment={completedExperiment} />,
    name: 'Completed with winner',
}

export const Draft: Story = {
    render: () => <ExperimentView experiment={draftExperiment} />,
    name: 'Draft experiment',
}

const sampleListData: ExperimentListData = {
    count: 3,
    results: [runningExperiment, completedExperiment, draftExperiment],
    _posthogUrl: 'https://us.posthog.com/project/1/experiments',
}

export const List: Story = {
    render: () => <ExperimentListView data={sampleListData} />,
    name: 'Experiment list',
}

const frequentistResults: ExperimentResultsData = {
    id: 'a4e1f2c3-0000-4000-8000-000000000001',
    experiment_id: 2,
    status: 'completed',
    total_metrics: 2,
    completed_metrics: 2,
    failed_metrics: 0,
    created_at: '2025-11-14T09:00:00Z',
    completed_at: '2025-11-14T09:05:00Z',
    query_to: '2025-11-14T09:00:00Z',
    result_source: 'recalculation',
    active_run: null,
    results: [
        {
            metric_uuid: 'b7c2d1e0-0000-4000-8000-000000000010',
            status: 'completed',
            result: {
                baseline: {
                    key: 'control',
                    number_of_samples: 5200,
                    sum: 312,
                    sum_squares: 312,
                    step_counts: [312],
                },
                variant_results: [
                    {
                        key: 'test-a',
                        method: 'frequentist',
                        number_of_samples: 5100,
                        sum: 410,
                        sum_squares: 410,
                        step_counts: [410],
                        p_value: 0.003,
                        significant: true,
                        confidence_interval: [0.011, 0.049],
                    },
                    {
                        key: 'test-b',
                        method: 'frequentist',
                        number_of_samples: 4900,
                        sum: 295,
                        sum_squares: 295,
                        step_counts: [295],
                        p_value: 0.92,
                        significant: false,
                        confidence_interval: [-0.019, 0.021],
                    },
                ],
            },
            error_message: null,
        },
        {
            metric_uuid: 'c8d3e2f1-0000-4000-8000-000000000011',
            status: 'completed',
            result: {
                baseline: {
                    key: 'control',
                    number_of_samples: 5200,
                    sum: 14560,
                    sum_squares: 61152,
                },
                variant_results: [
                    {
                        key: 'test-a',
                        method: 'frequentist',
                        number_of_samples: 5100,
                        sum: 15300,
                        sum_squares: 68850,
                        p_value: 0.041,
                        significant: true,
                        confidence_interval: [0.004, 0.196],
                    },
                    {
                        key: 'test-b',
                        method: 'frequentist',
                        number_of_samples: 4900,
                        sum: 13230,
                        sum_squares: 55566,
                        p_value: 0.38,
                        significant: false,
                        confidence_interval: [-0.083, 0.117],
                    },
                ],
            },
            error_message: null,
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/experiments/2',
}

const bayesianFallbackResults: ExperimentResultsData = {
    id: 'timeseries-fallback',
    experiment_id: 1,
    status: 'completed',
    total_metrics: 1,
    completed_metrics: 1,
    failed_metrics: 0,
    created_at: '2025-11-14T06:00:00Z',
    completed_at: '2025-11-14T06:00:00Z',
    query_to: '2025-11-13T23:59:00Z',
    result_source: 'timeseries_fallback',
    active_run: null,
    results: [
        {
            metric_uuid: 'd9e4f3a2-0000-4000-8000-000000000012',
            status: 'completed',
            result: {
                baseline: {
                    key: 'control',
                    number_of_samples: 840,
                    sum: 63,
                    sum_squares: 63,
                    step_counts: [63],
                },
                variant_results: [
                    {
                        key: 'test',
                        method: 'bayesian',
                        number_of_samples: 812,
                        sum: 74,
                        sum_squares: 74,
                        step_counts: [74],
                        chance_to_win: 0.86,
                        significant: false,
                        credible_interval: [-0.006, 0.038],
                    },
                ],
            },
            error_message: null,
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/experiments/1',
}

const legacyResults: ExperimentResultsData = {
    experiment: { id: 2, name: 'Pricing page CTA' },
    exposures: { control: 5200, 'test-a': 5100, 'test-b': 4900 },
    primaryMetricsResults: [
        [
            { variant: 'control', count: 312, probability: 0.12, significant: false },
            { variant: 'test-a', count: 410, probability: 0.87, significant: true },
            { variant: 'test-b', count: 295, probability: 0.01, significant: false },
        ],
    ],
    secondaryMetricsResults: [
        [
            { variant: 'control', count: 1050, probability: 0.45 },
            { variant: 'test-a', count: 1120, probability: 0.55 },
        ],
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/experiments/2',
}

export const Results: Story = {
    render: () => <ExperimentResultsView data={frequentistResults} />,
    name: 'Experiment results',
}

export const ResultsFallback: Story = {
    render: () => <ExperimentResultsView data={bayesianFallbackResults} />,
    name: 'Experiment results (preliminary)',
}

export const ResultsLegacy: Story = {
    render: () => <ExperimentResultsView data={legacyResults} />,
    name: 'Experiment results (legacy tool)',
}
