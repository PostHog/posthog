import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryObj } from '@storybook/react'

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
    parameters: {
        feature_flag_variants: [
            { key: 'control', name: 'Current flow', rollout_percentage: 50 },
            { key: 'test', name: 'Simplified flow', rollout_percentage: 50 },
        ],
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
    parameters: {
        feature_flag_variants: [
            { key: 'control', name: 'Get started', rollout_percentage: 34 },
            { key: 'test-a', name: 'Start free trial', rollout_percentage: 33 },
            { key: 'test-b', name: 'Try it now', rollout_percentage: 33 },
        ],
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
    parameters: {
        feature_flag_variants: [
            { key: 'control', rollout_percentage: 50 },
            { key: 'test', rollout_percentage: 50 },
        ],
    },
}

export const Running: Story = {
    render: () => <ExperimentView experiment={runningExperiment} />,
    storyName: 'Running experiment',
}

export const Completed: Story = {
    render: () => <ExperimentView experiment={completedExperiment} />,
    storyName: 'Completed with winner',
}

export const Draft: Story = {
    render: () => <ExperimentView experiment={draftExperiment} />,
    storyName: 'Draft experiment',
}

const sampleListData: ExperimentListData = {
    count: 3,
    results: [runningExperiment, completedExperiment, draftExperiment],
    _posthogUrl: 'https://us.posthog.com/project/1/experiments',
}

export const List: Story = {
    render: () => <ExperimentListView data={sampleListData} />,
    storyName: 'Experiment list',
}

const sampleResults: ExperimentResultsData = {
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
    render: () => <ExperimentResultsView data={sampleResults} />,
    storyName: 'Experiment results',
}
