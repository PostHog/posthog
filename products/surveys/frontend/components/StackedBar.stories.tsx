import type { Meta, StoryObj } from '@storybook/react'

import { StackedBar } from 'scenes/surveys/components/StackedBar'

const meta: Meta<typeof StackedBar> = {
    title: 'Surveys/Outcome bar',
    component: StackedBar,
    decorators: [
        (Story) => (
            <div className="w-128">
                <Story />
            </div>
        ),
    ],
    args: {
        segments: [
            { label: 'Detractors', count: 20, colorClass: 'bg-danger' },
            { label: 'Passives', count: 30, colorClass: 'bg-warning' },
            { label: 'Promoters', count: 50, colorClass: 'bg-success' },
        ],
        showTooltips: false,
        barValueFormatter: (count, total) => `${count} (${((count / total) * 100).toFixed(1)}%)`,
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const Nps: Story = {}

export const SmallSegment: Story = {
    args: {
        size: 'sm',
        showTooltips: true,
        segments: [
            { label: 'Responses', count: 1, colorClass: 'bg-success' },
            { label: 'Dismissed without answers', count: 699, colorClass: 'bg-warning' },
            { label: 'Unanswered', count: 300, colorClass: 'bg-muted' },
        ],
    },
}

export const SingleOutcome: Story = {
    args: {
        segments: [
            { label: 'Detractors', count: 0, colorClass: 'bg-danger' },
            { label: 'Passives', count: 0, colorClass: 'bg-warning' },
            { label: 'Promoters', count: 100, colorClass: 'bg-success' },
        ],
    },
}
