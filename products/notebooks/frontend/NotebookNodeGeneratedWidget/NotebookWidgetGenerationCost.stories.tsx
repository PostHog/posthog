import type { Meta, StoryObj } from '@storybook/react'

import { NotebookWidgetGenerationCost } from './NotebookWidgetGenerationCost'

const meta: Meta<typeof NotebookWidgetGenerationCost> = {
    title: 'Scenes-App/Notebooks/Widget generation cost',
    component: NotebookWidgetGenerationCost,
    decorators: [
        (Story) => (
            <div className="max-w-lg p-3">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof meta>

export const Recorded: Story = { args: { cost: '0.123456' } }
export const LessThanOneCent: Story = { args: { cost: '0.004200' } }
export const Unavailable: Story = { args: { cost: null } }
