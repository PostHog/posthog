import type { Meta, StoryObj } from '@storybook/react'

import { OptionSelector } from './OptionSelector'

const meta: Meta<typeof OptionSelector> = {
    title: 'Products/PostHog AI/OptionSelector',
    component: OptionSelector,
    // The global `^on[A-Z].*` action inference would inject an `onSkip` handler, which keeps the footer open.
    parameters: { actions: { argTypesRegex: null } },
    args: {
        options: [
            { label: 'Product analytics', value: 'Product analytics', description: 'Track product metrics and KPIs' },
            { label: 'Session replay', value: 'Session replay', description: 'Watch how people use the product' },
            { label: 'Feature flags', value: 'Feature flags' },
        ],
        onSelect: () => {},
        allowCustom: true,
        customPlaceholder: 'Type your answer...',
    },
    decorators: [
        (Story) => (
            <div className="w-128 border rounded p-3">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const CustomAnswerOpen: Story = {
    args: { selectedValue: 'Something else', initialCustomValue: 'Something else' },
}

export const WithSkip: Story = {
    args: { onSkip: () => {} },
}

export const NoDescriptions: Story = {
    args: {
        options: [
            { label: 'Weekly', value: 'Weekly' },
            { label: 'Monthly', value: 'Monthly' },
            { label: 'Quarterly', value: 'Quarterly' },
        ],
    },
}
