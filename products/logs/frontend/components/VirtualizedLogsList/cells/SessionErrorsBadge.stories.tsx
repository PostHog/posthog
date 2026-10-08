import { Meta, StoryObj } from '@storybook/react'

import { SessionErrorsBadge } from './SessionErrorsBadge'

const meta: Meta<typeof SessionErrorsBadge> = {
    title: 'Scenes-App/Logs/SessionErrorsBadge',
    component: SessionErrorsBadge,
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

type Story = StoryObj<typeof SessionErrorsBadge>

export const SeveralErrors: Story = {}

export const OneError: Story = {
    args: { errorCount: 1 },
}
