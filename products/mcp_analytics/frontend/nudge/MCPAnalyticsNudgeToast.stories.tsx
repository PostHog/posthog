import { Meta, StoryObj } from '@storybook/react'

import { MCPAnalyticsNudgeToast } from './MCPAnalyticsNudgeToast'

const meta: Meta<typeof MCPAnalyticsNudgeToast> = {
    title: 'Scenes-App/MCP Analytics/Nudge Toast',
    component: MCPAnalyticsNudgeToast,
    parameters: {
        // The component is normally rendered inside a react-toastify toast.
        // The decorator below approximates that container so the story is visually meaningful.
        layout: 'centered',
    },
    decorators: [
        (Story) => (
            <div className="max-w-md min-w-140 bg-surface-primary border border-primary rounded-lg shadow-lg p-3">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof MCPAnalyticsNudgeToast>

export const Default: Story = {
    args: { surface: 'insight' },
}
