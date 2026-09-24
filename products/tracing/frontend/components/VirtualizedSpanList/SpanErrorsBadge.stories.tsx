import { Meta, StoryObj } from '@storybook/react'

import { SpanErrorsBadge } from './SpanErrorsBadge'

const meta: Meta<typeof SpanErrorsBadge> = {
    title: 'Products/Tracing/SpanErrorsBadge',
    component: SpanErrorsBadge,
    args: {
        tier: 'span',
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

type Story = StoryObj<typeof SpanErrorsBadge>

export const SpanTier: Story = {}

export const TraceTier: Story = {
    args: { tier: 'trace', errorCount: 2 },
}

export const SessionTier: Story = {
    args: { tier: 'session', errorCount: 5 },
}

export const OneError: Story = {
    args: { errorCount: 1 },
}

// A trace where one SDK stamped a trace id and another did not.
export const TraceTierWithMoreInSession: Story = {
    args: { tier: 'trace', errorCount: 1, alsoInSession: 3 },
}
