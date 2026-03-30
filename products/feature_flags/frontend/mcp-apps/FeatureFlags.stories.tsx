import { McpThemeDecorator } from '@common/mosaic/storybook/decorator'
import type { Meta, StoryObj } from '@storybook/react'

import { type FeatureFlagData, type FeatureFlagListData, FeatureFlagListView, FeatureFlagView } from './index'

const meta: Meta = {
    title: 'MCP Apps/Feature Flags',
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

const sampleBooleanFlag: FeatureFlagData = {
    id: 1,
    key: 'enable-new-dashboard',
    name: 'New dashboard experience',
    description: 'Enables the redesigned dashboard for selected users.',
    active: true,
    filters: {
        groups: [
            {
                properties: [{ key: 'email', value: '@posthog.com', operator: 'icontains', type: 'person' }],
                rollout_percentage: 100,
            },
            {
                properties: [],
                rollout_percentage: 50,
            },
        ],
    },
    tags: ['frontend', 'experiment'],
    updated_at: '2025-12-15T14:30:00Z',
    _posthogUrl: 'https://us.posthog.com/project/1/feature_flags/1',
}

const sampleMultivariateFlag: FeatureFlagData = {
    id: 2,
    key: 'checkout-flow-variant',
    name: 'Checkout flow experiment',
    description: 'A/B/C test for the checkout experience.',
    active: true,
    filters: {
        groups: [
            {
                properties: [{ key: 'plan', value: 'enterprise', operator: 'exact', type: 'person' }],
                rollout_percentage: 100,
                variant: 'test-a',
            },
            {
                properties: [],
                rollout_percentage: 80,
            },
        ],
        multivariate: {
            variants: [
                { key: 'control', name: 'Current flow', rollout_percentage: 50 },
                { key: 'test-a', name: 'Streamlined', rollout_percentage: 30 },
                { key: 'test-b', name: 'One-page', rollout_percentage: 20 },
            ],
        },
    },
    tags: ['checkout', 'growth'],
    updated_at: '2025-12-20T09:00:00Z',
    _posthogUrl: 'https://us.posthog.com/project/1/feature_flags/2',
}

const sampleInactiveFlag: FeatureFlagData = {
    id: 3,
    key: 'deprecated-feature',
    name: 'Old feature toggle',
    active: false,
    filters: {
        groups: [
            {
                properties: [],
                rollout_percentage: 0,
            },
        ],
    },
    updated_at: '2024-06-01T00:00:00Z',
}

export const BooleanFlag: Story = {
    render: () => <FeatureFlagView flag={sampleBooleanFlag} />,
    storyName: 'Boolean flag',
}

export const MultivariateFlag: Story = {
    render: () => <FeatureFlagView flag={sampleMultivariateFlag} />,
    storyName: 'Multivariate flag with variant override',
}

export const InactiveFlag: Story = {
    render: () => <FeatureFlagView flag={sampleInactiveFlag} />,
    storyName: 'Inactive flag',
}

const sampleListData: FeatureFlagListData = {
    count: 3,
    next: null,
    previous: null,
    results: [sampleBooleanFlag, sampleMultivariateFlag, sampleInactiveFlag],
    _posthogUrl: 'https://us.posthog.com/project/1/feature_flags',
}

export const FlagList: Story = {
    render: () => <FeatureFlagListView data={sampleListData} />,
    storyName: 'Flag list',
}
