import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryObj } from '@storybook/react'

import { LLMCostsView, type LLMCostsData } from './index'

const meta: Meta = {
    title: 'MCP Apps/LLM Analytics',
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

const multiModelData: LLMCostsData = {
    results: [
        {
            label: 'gpt-4o',
            count: 3,
            data: [12.5, 14.2, 11.8],
            labels: ['2025-12-01', '2025-12-02', '2025-12-03'],
            days: ['2025-12-01', '2025-12-02', '2025-12-03'],
            aggregated_value: 38.5,
            breakdown_value: 'gpt-4o',
        },
        {
            label: 'claude-3-5-sonnet',
            count: 3,
            data: [8.3, 9.1, 7.6],
            labels: ['2025-12-01', '2025-12-02', '2025-12-03'],
            days: ['2025-12-01', '2025-12-02', '2025-12-03'],
            aggregated_value: 25.0,
            breakdown_value: 'claude-3-5-sonnet',
        },
        {
            label: 'gpt-4o-mini',
            count: 3,
            data: [1.2, 1.5, 0.9],
            labels: ['2025-12-01', '2025-12-02', '2025-12-03'],
            days: ['2025-12-01', '2025-12-02', '2025-12-03'],
            aggregated_value: 3.6,
            breakdown_value: 'gpt-4o-mini',
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/llm-analytics',
}

const singleModelData: LLMCostsData = {
    results: [
        {
            label: 'claude-3-5-sonnet',
            count: 5,
            data: [4.2, 5.1, 3.8, 6.0, 4.5],
            labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'],
            days: ['2025-12-01', '2025-12-02', '2025-12-03', '2025-12-04', '2025-12-05'],
            aggregated_value: 23.6,
            breakdown_value: 'claude-3-5-sonnet',
        },
    ],
    _posthogUrl: 'https://us.posthog.com/project/1/llm-analytics',
}

const emptyData: LLMCostsData = {
    results: [],
    _posthogUrl: 'https://us.posthog.com/project/1/llm-analytics',
}

export const MultiModel: Story = {
    render: () => <LLMCostsView data={multiModelData} />,
    storyName: 'Multiple models',
}

export const SingleModel: Story = {
    render: () => <LLMCostsView data={singleModelData} />,
    storyName: 'Single model',
}

export const Empty: Story = {
    render: () => <LLMCostsView data={emptyData} />,
    storyName: 'No data',
}
