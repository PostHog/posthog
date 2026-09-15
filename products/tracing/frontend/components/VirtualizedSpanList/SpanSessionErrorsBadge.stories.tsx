import { Meta, StoryObj } from '@storybook/react'

import { SpanSessionErrorsBadge } from './SpanSessionErrorsBadge'

const meta: Meta<typeof SpanSessionErrorsBadge> = {
    title: 'Products/Tracing/SpanSessionErrorsBadge',
    component: SpanSessionErrorsBadge,
    args: {
        errorCount: 3,
        onClick: () => {},
    },
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof SpanSessionErrorsBadge>

export const SeveralErrors: Story = {}

export const OneError: Story = {
    args: { errorCount: 1 },
}
